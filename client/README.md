# OpenSlides 3 Client

Prototype application for OpenSlides 3.0 (Client).
Currently under constant heavy maintenance.

## Development Info

As an Angular project, Angular CLI is highly recommended to create components and services.
See https://angular.io/guide/quickstart for details.

### Contribution Info

Please respect the code-style defined in `.editorconf` and `.pretierrc`.

Code alignment should be automatically corrected by the pre-commit hooks.
Adjust your editor to the `.editorconfig` to avoid surprises.
See https://editorconfig.org/ for details.

### Pre-Commit Hooks

Before commiting, new code will automatically be aligned to the definitions set in the
`.prettierrc`.
Furthermore, new code has to pass linting.

Our pre-commit hooks are:
`pretty-quick --staged` and `lint`
See `package.json` for details.

### Documentation Info

The documentation can be generated by running `npm run compodoc`.
A new web server will be started on http://localhost:8080
Once running, the documentation will be updated automatically.

You can run it on another port, with adding your local port after the
command. If no port specified, it will try to use 8080.

Please document new code using JSDoc tags.
See https://compodoc.app/guides/jsdoc-tags.html for details.

### Development server

Run `npm start` for a development server. Navigate to `http://localhost:4200/`.
The app will automatically reload if you change any of the source files.

A running OpenSlides (2.2 or higher) instance is expected on port 8000.

Start OpenSlides as usual using
`python manage.py start --no-browser --host 0.0.0.0`

### Translation

We are using ngx-translate for translation purposes.
Use `npm run extract` to extract strings and update elements an with translation functions.

Language files can be found in `/src/assets/i18n`.