# Job Ad Crawler for JobsDB

This is a Node.js crawler that scrapes IT job advertisements from JobsDB website.

## Features

- Crawls job listings and details from hk.jobsdb.com
- Uses Playwright (headless Chromium) for robust scraping
- Stores data in SQLite database
- Saves job data as JSON files
- Handles pagination and duplicate detection
- Implements retry logic for failed requests

## Setup

1. Install dependencies:
   ```
   npm install
   ```

2. Configure environment variables in `.env` file:
   ```
   APP_ENV=local
   MAX_FETCH_PAGE=2
   DELAY_BETWEEN_FETCH_DETAIL=1000
   OUTPUT_FOLDER=./output/
   OUTPUT_LOG_FOLDER=./output/
   OUTPUT_SQLITE_DB_FILE=./output/hk-it-job-ad-analysis.db
   ```

## Usage

```bash
# Development mode
npm start

# Production mode
npm run prod

# Proof of concept
npm run poc
```

## Important Notes

The website implements anti-bot measures that may prevent successful scraping. 
If you encounter 403 Forbidden errors, this indicates the site is actively blocking automated requests.

## Implementation Details

- **Scraping Method**: Headless Chromium via Playwright
- **Data Storage**: SQLite (default)
- **Error Handling**: Retry logic, timeouts, graceful degradation
- **Rate Limiting**: Delays between requests to respect server resources