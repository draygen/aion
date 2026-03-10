const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './qa/playwright',
  timeout: 30_000,
  use: {
    baseURL: process.env.JARVIS_BASE_URL || 'http://127.0.0.1:8081',
    trace: 'retain-on-failure',
  },
  reporter: [['list']],
});
