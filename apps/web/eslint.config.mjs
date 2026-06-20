// eslint-config-next v16 ships a native flat-config array; its default entry already bundles
// core-web-vitals + the TypeScript rules + sensible ignores (.next, next-env.d.ts, …).
import next from "eslint-config-next";

/** @type {import('eslint').Linter.Config[]} */
const eslintConfig = [...next];

export default eslintConfig;
