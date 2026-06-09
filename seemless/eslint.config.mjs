import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const configs = Array.isArray(nextCoreWebVitals)
  ? nextCoreWebVitals
  : [nextCoreWebVitals];

const eslintConfig = [
  { ignores: [".next/**", "node_modules/**"] },
  ...configs,
  {
    rules: {
      "@next/next/no-img-element": "off",
    },
  },
];

export default eslintConfig;
