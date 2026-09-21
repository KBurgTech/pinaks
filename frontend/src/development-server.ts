const djangoDevelopmentServer = "http://127.0.0.1:8000";

export const developmentServer = {
  proxy: {
    "/accounts": djangoDevelopmentServer,
    "/api": djangoDevelopmentServer,
  },
};
