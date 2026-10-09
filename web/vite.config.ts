import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` talks to the real judge: /api/* is proxied to the site, and if
// the CLI has signed in (~/.config/mogi/config.json) its token rides along as a
// Bearer header, so the dev server shows real data without a cookie.
function devToken(): string | undefined {
  try {
    const cfg = JSON.parse(readFileSync(process.env.MOGI_CONFIG || join(homedir(), ".config/mogi/config.json"), "utf8"));
    return cfg.token;
  } catch {
    return undefined;
  }
}
const SITE = process.env.MOGI_SITE || "https://d24vqc5jsqa7l8.cloudfront.net";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: SITE,
        changeOrigin: true,
        configure(proxy) {
          const token = devToken();
          proxy.on("proxyReq", req => { if (token) req.setHeader("authorization", `Bearer ${token}`); });
        },
      },
    },
  },
  build: {
    target: "es2022",
    rollupOptions: {
      output: {
        manualChunks: {
          editor: ["codemirror", "@codemirror/lang-python", "@codemirror/view", "@codemirror/state",
                   "@codemirror/language", "@codemirror/commands", "@lezer/highlight"],
          motion: ["motion"],
        },
      },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
