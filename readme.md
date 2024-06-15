## 
run for local production
```bash
npm run --prefix "C:\github_repos\hk-it-job-ad-analysis\job-ad-crawler-jobsdb" prod
```

## docker command

```
docker build . -t job-ad-crawler-jobsdb -t job-ad-crawler-jobsdb:1.0.1
docker run -e MONGO_DB_URL="mongodb://172.17.0.2:27017/jobsdb_ad" job-ad-crawler-jobsdb:1.0.1
```

## mongodb

### run mongodb container

```bash
docker run --name mongo -p 27017:27017 -v mongo-data:/data/db -d mongo:7.0.11
```

### init mongodb database and collection

```bash
mongosh "mongodb://127.0.0.1:27017/jobsdb_ad" --eval "db.createCollection('jobsdb_ad')"
mongosh "mongodb://127.0.0.1:27017/jobsdb_ad" --eval "db.jobsdb_ad.createIndex({ job_id: -1 })"
mongosh "mongodb://127.0.0.1:27017/jobsdb_ad" --eval "db.jobsdb_ad.createIndex({ job_detail_html_fetched: 1 })"
```

### shrink mongodb size

```
mongosh "mongodb://127.0.0.1:27017/jobsdb_ad" --eval "db.runCommand({ compact: 'jobsdb_ad' })"
```
