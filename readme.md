# HK IT JOB advertisement Analysis

This is a project that analysis hong kong IT job ad. Scrape data from job ad website, analysis keyword and keyword relationship, show on dashboard.

## Workflow
  - Daily
    - trigger scraper to scrape job ad and store result in cloudflare R2 storage.
    - Use NER (Name Entity Recognition) extract keyword and store result in cloudflare R2 storage.
  - Monthly
    - analysis keyword ranking and keyword relationship
    - generate a html page dashboard to show it.

## Env

- Testing  
  This program run on local, store result in local folder, allow to trigger by command.  
- Production
  This program run on cloudflare, use cloudflare worker to run scraper and provide .