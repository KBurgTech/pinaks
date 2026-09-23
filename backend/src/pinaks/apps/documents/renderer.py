"""Constrained visual template rendering; no application objects enter the template context."""

import base64
import re
from datetime import date
from decimal import Decimal
from html import escape
from multiprocessing import Process, Queue
from queue import Empty

from jinja2 import Environment, StrictUndefined, TemplateError, nodes
from jinja2.sandbox import SandboxedEnvironment

MAX_SOURCE = 100_000
MAX_OUTPUT = 250_000
MAX_EMBEDDED_OUTPUT = 5_000_000
MAX_PDF = 5_000_000
PDF_TIMEOUT = 10
_UNSAFE_MARKUP = re.compile(
    r"<\s*/?\s*(?:script|iframe|object|embed|form|input|base|link|meta|svg)\b"
    r"|\bon[a-z]+\s*=|@import\b|url\s*\(|"
    r"(?:https?:|file:|ftp:|javascript:|data:|\\\\|\.\./)",
    re.I,
)
_RESOURCE_ATTR = re.compile(r"\b(?:src|href)\s*=", re.I)
_ASSET_REFERENCE = re.compile(r'<img\s+src="asset:([a-zA-Z0-9_./-]+)"\s*/?>', re.I)
_ALLOWED_ROOTS = {"invoice", "seller", "customer", "recipient", "labels", "line"}
_ALLOWED_FILTERS = {"money", "date"}


class PreviewRenderError(ValueError):
    pass


def _money(value: Decimal | str, language: str) -> str:
    amount = Decimal(str(value))
    result = f"{amount:,.2f}"
    return result.replace(",", " ").replace(".", ",") if language == "de" else result


def _date(value: date | str, language: str) -> str:
    parsed = value if isinstance(value, date) else date.fromisoformat(value)
    return parsed.strftime("%d.%m.%Y" if language == "de" else "%Y-%m-%d")


def _check_ast(node: nodes.Node) -> None:
    allowed = (
        nodes.Template,
        nodes.Output,
        nodes.TemplateData,
        nodes.Name,
        nodes.Getattr,
        nodes.Filter,
        nodes.For,
    )
    if not isinstance(node, allowed):
        raise PreviewRenderError("Template syntax is not allowed.")
    if isinstance(node, nodes.Name) and node.name not in _ALLOWED_ROOTS:
        raise PreviewRenderError("Unknown template variable.")
    if isinstance(node, nodes.Getattr) and (
        node.attr.startswith("_") or not re.fullmatch(r"[a-z][a-z0-9_]*", node.attr)
    ):
        raise PreviewRenderError("Template attribute is not allowed.")
    if isinstance(node, nodes.Filter) and (
        node.name not in _ALLOWED_FILTERS or node.args or node.kwargs
    ):
        raise PreviewRenderError("Template filter is not allowed.")
    if isinstance(node, nodes.For):
        if (
            not isinstance(node.target, nodes.Name)
            or node.target.name != "line"
            or node.recursive
            or node.test
            or node.else_
        ):
            raise PreviewRenderError("Only line loops are allowed.")
        if not (
            isinstance(node.iter, nodes.Getattr)
            and node.iter.attr == "lines"
            and isinstance(node.iter.node, nodes.Name)
            and node.iter.node.name == "invoice"
        ):
            raise PreviewRenderError("Only invoice lines may be iterated.")
    for child in node.iter_child_nodes():
        _check_ast(child)


def render_preview_html(
    source: str,
    css: str,
    *,
    language: str,
    context: dict[str, object],
    assets: dict[str, tuple[str, bytes]] | None = None,
) -> str:
    if language not in {"en", "de"} or len(source) + len(css) > MAX_SOURCE:
        raise PreviewRenderError("Invalid or oversized template.")
    if _UNSAFE_MARKUP.search(source) or _UNSAFE_MARKUP.search(css):
        raise PreviewRenderError("Unsafe markup or resource reference.")
    references = list(_ASSET_REFERENCE.finditer(source))
    if len(references) != len(_RESOURCE_ATTR.findall(source)):
        raise PreviewRenderError("Unsupported resource reference.")
    allowed_assets = assets or {}
    for reference in references:
        if reference.group(1) not in allowed_assets:
            raise PreviewRenderError("Missing or undeclared image asset.")
    environment: Environment = SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)
    environment.filters.clear()
    environment.filters.update(
        {
            "money": lambda value: _money(value, language),
            "date": lambda value: _date(value, language),
        }
    )
    try:
        parsed = environment.parse(source)
        _check_ast(parsed)
        if sum(1 for _ in parsed.find_all(nodes.For)) > 1:
            raise PreviewRenderError("Only one line loop is allowed.")
        body = environment.from_string(source).render(context)
        if len(body) > MAX_OUTPUT:
            raise PreviewRenderError("Rendered preview is too large.")
        for reference in references:
            key = reference.group(1)
            content_type, payload = allowed_assets[key]
            encoded = base64.b64encode(payload).decode("ascii")
            body = body.replace(f"asset:{key}", f"data:{content_type};base64,{encoded}")
    except (TemplateError, ValueError, TypeError, ArithmeticError) as error:
        raise PreviewRenderError("Template could not be rendered.") from error
    if len(body) > MAX_EMBEDDED_OUTPUT:
        raise PreviewRenderError("Embedded preview is too large.")
    watermark = "PREVIEW — NOT AN INVOICE" if language == "en" else "VORSCHAU — KEINE RECHNUNG"
    return (
        '<!doctype html><html lang="' + language + '"><head><meta charset="utf-8">'
        "<style>"
        + css
        + '</style></head><body><aside style="border:2px solid #a00;padding:8px">'
        + escape(watermark)
        + "</aside>"
        + body
        + "</body></html>"
    )


def _pdf_worker(html: str, result: Queue[bytes | str]) -> None:
    from weasyprint import HTML  # type: ignore[import-untyped]

    def blocked_fetcher(url: str) -> dict[str, object]:
        match = re.fullmatch(r"data:(image/(?:png|jpeg));base64,([A-Za-z0-9+/=]+)", url)
        if match is None:
            raise ValueError("External resources are disabled.")
        payload = base64.b64decode(match.group(2), validate=True)
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError("Image asset is too large.")
        return {"string": payload, "mime_type": match.group(1)}

    try:
        pdf = HTML(string=html, url_fetcher=blocked_fetcher).write_pdf()
        result.put(pdf if len(pdf) <= MAX_PDF else "too_large")
    except Exception:
        result.put("render_failed")


def render_preview_pdf(html: str) -> bytes:
    queue: Queue[bytes | str] = Queue(maxsize=1)
    process = Process(target=_pdf_worker, args=(html, queue))
    process.start()
    try:
        result = queue.get(timeout=PDF_TIMEOUT)
    except Empty as error:
        process.terminate()
        raise PreviewRenderError("PDF rendering timed out.") from error
    finally:
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join()
        queue.close()
    if not isinstance(result, bytes):
        raise PreviewRenderError("PDF rendering failed or exceeded the size limit.")
    return result
