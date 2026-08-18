import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["web/dist", "web/public/data", "node_modules", ".venv"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.strictTypeChecked,
      ...tseslint.configs.stylisticTypeChecked,
      // eslint-plugin-react-hooks 7 keeps the eslintrc-shaped entries at the top level and
      // the flat-config ones under `.flat`; only the latter is usable here.
      reactHooks.configs.flat["recommended-latest"],
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // Artifact payloads arrive as `unknown` and are narrowed by the loader's own guards;
      // that is the point of the loader, so the guards themselves need explicit checks
      // rather than blanket assertions.
      "@typescript-eslint/no-unnecessary-condition": "off",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { fixStyle: "inline-type-imports" },
      ],
    },
  },
  {
    files: ["vite.config.ts", "eslint.config.js"],
    extends: [tseslint.configs.disableTypeChecked],
  },
);
