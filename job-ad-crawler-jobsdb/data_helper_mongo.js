"use strict";
const { MongoClient } = require("mongodb");
class data_helper_mongo {
  async init_db_client() {
    try {
      let url = process.env.MONGO_DB_URL;
      let db_name = process.env.MONGO_DB_NAME;
      let col_name = process.env.MONGO_COL_NAME;

      console.log("mongodb url: " + url);
      console.log("mongodb db name: " + db_name);
      console.log("mongodb collection name: " + col_name);

      let mongo_client = new MongoClient(url, {});
      await mongo_client.connect();
      let mongo_db = mongo_client.db(db_name);
      let mongo_col = mongo_db.collection(col_name);

      this.client = mongo_client;
      this.db = mongo_db;
      this.col = mongo_col;
    } catch (error) {
      console.error("Error connecting to MongoDB.");
      throw error;
    }
  }
  async get_last_job_id() {
    let result = await this.col.find({}).sort({ job_id: -1 }).limit(1);
    let docs = await result.toArray();
    let last_job_id = docs?.[0]?.job_id;
    return last_job_id || 0;
  }
  async get_existed_job_id_list(jobs) {
    let job_id_array = jobs.map((job) => job.job_id);
    let result = this.col.find({ job_id: { $in: job_id_array } }).project({ job_id: 1, _id: 0 });
    let exsited_job_list = await result.toArray();
    let exsited_job_id_list = exsited_job_list.map((j) => j.job_id);
    return exsited_job_id_list;
  }
  async insert_many(jobs) {
    try {
      await this.col.insertMany(jobs, { ordered: true });
    } catch (error) {
      console.error("Error insert jobs to MongoDB.");
      throw error;
    }
  }
  async close() {
    await this.client.close();
  }
}

exports.data_helper = new data_helper_mongo();