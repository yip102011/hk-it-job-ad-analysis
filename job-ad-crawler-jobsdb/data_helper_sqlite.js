import { DatabaseSync, DatabaseSyncOptions } from 'node:sqlite';

class data_helper_sqlite {
  init_db_client() {
    let db_path = process.env.OUTPUT_SQLITE_DB_FILE;
    if (!db_path) {
      throw new Error("env var OUTPUT_SQLITE_DB_FILE is not defined");
    }
    this.db = new DatabaseSync(db_path, new DatabaseSyncOptions());

    this.db.exec(`
      CREATE TABLE IF NOT EXISTS jobsdb_ad (
        job_id INTEGER PRIMARY KEY DESC,
        job_id_text TEXT,
        job_title TEXT,
        job_link TEXT,
        company_name TEXT,
        company_link TEXT,
        location_1 TEXT,
        location_2 TEXT,
        salary TEXT,
        job_sub_category TEXT,
        job_category TEXT,
        job_desc_1 TEXT,
        job_desc_2 TEXT,
        job_desc_3 TEXT,
        post_at TEXT,
        contact TEXT,
        job_detail_html TEXT,
        job_detail_html_fetched INTEGER
      )
    `);

    this.db.exec(`CREATE INDEX IF NOT EXISTS idx_job_detail_html_fetched ON jobsdb_ad (job_detail_html_fetched)`);
  }

  get_last_job_id() {
    const row = this.db.prepare("SELECT job_id FROM jobsdb_ad ORDER BY job_id DESC LIMIT 1").get();
    return row ? row.job_id : 0;
  }

  get_existed_job_id_list(jobs) {
    let jobIds = jobs.map((job) => job.job_id);
    let placeholders = jobIds.map(() => "?").join(",");
    const stmt = this.db.prepare(`SELECT job_id FROM jobsdb_ad WHERE job_id IN (${placeholders})`);
    const rows = stmt.all(...jobIds);
    return rows.map((row) => row.job_id);
  }

  /**
   * return db changed record
   * @param {[]} jobs
   * @returns {Number}
   */
  insert_many(jobs) {
    if (jobs.length === 0) {
      return 0; // Return 0 changes if no jobs to insert
    }

    let placeholders = jobs.map((job) => `(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).join(",");
    let values = jobs.flatMap((job) => [
      job.job_id,
      job.job_id_text,
      job.job_title,
      job.job_link,
      job.company_name,
      job.company_link,
      job.location_1,
      job.location_2,
      job.salary,
      job.job_sub_category,
      job.job_category,
      job.job_desc_1,
      job.job_desc_2,
      job.job_desc_3,
      job.post_at?.toISOString(),
      job.contact,
      job.job_detail_html,
      job.job_detail_html_fetched,
    ]);

    let sql = "INSERT OR IGNORE INTO jobsdb_ad (job_id, job_id_text, job_title, job_link, company_name, company_link, location_1, location_2, salary, job_sub_category, job_category, job_desc_1, job_desc_2, job_desc_3, post_at, contact, job_detail_html, job_detail_html_fetched) VALUES " + placeholders;

    const stmt = this.db.prepare(sql);
    const result = stmt.run(...values);
    return result.changes;
  }

  close() {
    this.db?.close();
  }
}

export const data_helper = new data_helper_sqlite();
