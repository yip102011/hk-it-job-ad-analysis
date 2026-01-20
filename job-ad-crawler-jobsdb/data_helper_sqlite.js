import sqlite3 from "sqlite3";

class data_helper_sqlite {
  async init_db_client() {
    let db_path = process.env.OUTPUT_SQLITE_DB_FILE;
    if (!db_path) {
      throw new Error("env var OUTPUT_SQLITE_DB_FILE is not defined");
    }

    this.db = new sqlite3.Database(db_path);
    await this.runAsync(`
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

    await this.runAsync(`CREATE INDEX IF NOT EXISTS idx_job_detail_html_fetched ON jobsdb_ad (job_detail_html_fetched)`);
  }
  async runAsync(sql) {
    return new Promise((resolve, reject) => {
      this.db.run(sql, (err) => {
        if (err) {
          reject(err);
        } else {
          resolve();
        }
      });
    });
  }
  async get_last_job_id() {
    return new Promise((resolve, reject) => {
      this.db.get("SELECT job_id FROM jobsdb_ad ORDER BY job_id DESC LIMIT 1", (err, row) => {
        if (err) {
          reject(err);
        } else {
          resolve(row ? row.job_id : 0);
        }
      });
    });
  }
  async get_existed_job_id_list(jobs) {
    return new Promise((resolve, reject) => {
      let jobIds = jobs.map((job) => job.job_id);
      let placeholders = jobIds.map(() => "?").join(",");
      this.db.all(`SELECT job_id FROM jobsdb_ad WHERE job_id IN (${placeholders})`, jobIds, (err, rows) => {
        if (err) {
          reject(err);
        } else {
          let existedJobIds = rows.map((row) => row.job_id);
          resolve(existedJobIds);
        }
      });
    });
  }
  /**
   * return db changed record
   * @param {[]} jobs
   * @returns {Promise<Number>}
   */
  async insert_many(jobs) {
    return new Promise((resolve, reject) => {
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

      let sql = `
        INSERT INTO jobsdb_ad (
          job_id, job_id_text, job_title, job_link, company_name, company_link, location_1, location_2,
          salary, job_sub_category, job_category, job_desc_1, job_desc_2, job_desc_3,
          post_at, contact, job_detail_html, job_detail_html_fetched
        ) VALUES ${placeholders}
        ON CONFLICT(job_id) 
        DO NOTHING;
      `;

      let callback = (err) => {
        if (err) {
          reject(err);
        } else {
          resolve(this.changes);
        }
      };

      this.db.run(sql, values, callback);
    });
  }
  async close() {
    this.db?.close();
  }
}

export const data_helper = new data_helper_sqlite();
