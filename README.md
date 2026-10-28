### Waba

End-to-end WhatsApp Cloud API integration for Frappe/ERPNext: several WhatsApp Business Accounts, several numbers per account, agents working a shared inbox, templates, attachments and conversations linked to Leads, Contacts and Customers. Talks to Meta's Cloud API directly (no intermediary provider).

**Status: under development, not yet released.**

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench --site $SITE install-app waba
```

### Updating an existing site

```bash
cd $PATH_TO_YOUR_BENCH/apps/waba && git pull
cd $PATH_TO_YOUR_BENCH
bench --site $SITE migrate        # creates doctypes and re-applies the app's configuration
# then restart the web and worker processes and clear the cache
```

All configuration the app needs is created by its own migrate step and patches, never by hand in the Desk, so a migrate on any site brings it to the same state.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/waba
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
