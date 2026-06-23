module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  plugins: ['@typescript-eslint', 'react'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'prettier',
  ],
  settings: { react: { version: 'detect' } },
  rules: { 'react/react-in-jsx-scope': 'off' },
  env: { browser: true, node: true, es2022: true },
};
