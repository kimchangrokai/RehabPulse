# Scoped sync, parallel sessions, and health

## Purpose

Lookup, reporting, and mailing are per project. Lookup time and mail time are separate. Projects run as independent OS processes so hundreds of cases with vision captcha can proceed in parallel.

## CLI

- `sync` / `report` without `--company` and without `--project` exit with an error and do not hit the portal
- `--company` alone runs each project under that company as a separate process
- `--company` and `--project` together run that one project

## Sidecar YAML

Path: `data/{company}/{project}.yaml`

```yaml
lookup_time: "04:00"
mail_time: "07:00"
```

New projects get those defaults. Times may be changed per project.

## Windows tasks (weekdays)

- One lookup task per project at `lookup_time` (default 04:00)
- One mail/report task per project at `mail_time` (default 07:00)
- Tasks for different projects may overlap; each has its own Python process, browser, and captcha client
- Weekdays only (court business days). Weekends skip lookup, mail, and operator alerts

## Health and retries

Before sending mail at `mail_time`:

1. Build the day's report from the project workbook (no portal). `sync` writes `reports/{company}/{project}/{YYYY-MM-DD}.md` after a full-project save; `--case` and a locked primary xlsx do not seal that file
2. If SMTP fails, retry twice
3. After retries, any remaining issue mails the operator `realtyscope.ai@gmail.com`, including:
   - report still missing
   - SMTP still failing
   - lookup `error`
   - lookup `miss` (not-found day)
