module.exports = {
  ci: {
    collect: {
      numberOfRuns: 1,
      url: ["http://localhost:3000/"],
      startServerCommand: "npm run start",
      startServerReadyPattern: "ready - started server on",
      startServerReadyTimeout: 120000,
      settings: {
        preset: "desktop",
        onlyCategories: ["performance", "accessibility", "best-practices", "seo"],
        extraHeaders: JSON.stringify({
          "x-rm-public-path": "1",
        }),
      },
    },
    assert: {
      assertions: {
        "categories:performance": ["warn", { minScore: 0.8 }],
        "categories:accessibility": ["warn", { minScore: 0.9 }],
        "categories:best-practices": ["warn", { minScore: 0.9 }],
        "categories:seo": ["warn", { minScore: 0.9 }],
      },
      assertionsByUrl: {},
    },
    upload: {
      target: "temporary-public-storage",
    },
  },
};
