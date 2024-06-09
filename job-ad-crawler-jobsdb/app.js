const jsdom = require("jsdom");
const { JSDOM } = jsdom;
const { MongoClient } = require("mongodb");

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
function get_now() {
  let now = new Date();
  let now_str = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().replace(/[TZ]/g, " ");
  return now_str;
}
function calculate_datetime(time_text) {
  if (!time_text) {
    return null;
  }
  let time_regex = /(\d+)([mhd])/;
  let match = time_text.match(time_regex);

  if (match) {
    let amount = parseInt(match[1]);
    let unit = match[2];
    let now_ms = new Date().getTime();

    switch (unit) {
      case "m":
        return new Date(now_ms - (now_ms % 60000) - amount * 60000);
      case "h":
        return new Date(now_ms - (now_ms % 3600000) - amount * 3600000);
      case "d":
        return new Date(now_ms - (now_ms % 86400000) - amount * 86400000);
      default:
        return null;
    }
  } else {
    return null;
  }
}
function extract_contact(job_detail_ele) {
  let contact_ele = job_detail_ele?.querySelector("[data-contact-match]");
  let contact = "";
  if (contact_ele) {
    let href = contact_ele.getAttribute("href");
    if (href.startsWith("/cdn-cgi/l/email-protection")) {
      contact = decode_protected_email(href);
    } else {
      contact = contact_ele.textContent;
    }
  }
  return contact;
}
function decode_protected_email(href) {
  var href = "/cdn-cgi/l/email-protection#67060b0b02094917080809270a06091708100215001504490f0c";
  var c = "/cdn-cgi/l/email-protection#".length;
  var a = parseInt(href.substr(c, 2), 16);
  var i = c + 2;
  for (var str = ""; i < href.length; i += 2) {
    var l = parseInt(href.substr(i, 2), 16) ^ a;
    str += String.fromCharCode(l);
  }
  str = decodeURIComponent(escape(str));
  return str;
}
async function save_jobs_to_file(jobs) {
  const fs = require("fs").promises;
  let json_string = JSON.stringify(jobs, null, 2);
  await fs.writeFile("jobs.json", json_string, "utf-8");
}
async function init_mongo_client() {
  const url = process.env.MONGO_DB_URL;
  console.log("mongodb url: " + url);

  const db_name = process.env.MONGO_DB_NAME;
  console.log("mongodb db name: " + db_name);

  let col_name = process.env.MONGO_COL_NAME;
  console.log("mongodb collection name: " + col_name);

  const mongo_client = new MongoClient(url, {});
  await mongo_client.connect();
  const mongo_db = mongo_client.db(db_name);
  const mongo_col = mongo_db.collection(col_name);
  return [mongo_client, mongo_db, mongo_col];
}
async function extract_job_list(html_string) {
  let dom = new JSDOM(html_string);
  let article_list = dom.window.document.querySelectorAll("article[data-job-id]");

  // extract job field from html
  let jobs = [];
  for (let i = 0; i < article_list.length; i++) {
    let article = article_list[i];
    let job_id_text = article.getAttribute("data-job-id");
    let job_id = Number(job_id_text);
    let job_title = article.querySelector('[data-automation="jobTitle"]')?.textContent;
    let job_link = article.querySelector('[data-automation="job-list-view-job-link"]')?.getAttribute("href");

    let company_ele = article.querySelector('[data-automation="jobCompany"]');
    let company_name = company_ele?.textContent;
    let company_link = company_ele?.getAttribute("href");

    let locations_ele = article.querySelectorAll('[data-automation="jobCardLocation"]');
    if (locations_ele.length == 1) {
      var location_1 = locations_ele?.[0]?.textContent.replace(",", "").replace(" ", "");
    } else if (locations_ele.length == 2) {
      var location_1 = locations_ele?.[1]?.textContent.replace(",", "").replace(" ", "");
      var location_2 = locations_ele?.[0]?.textContent.replace(",", "").replace(" ", "");
    }

    //get text from data-automation="jobSalary"
    let salary = article.querySelector('[data-automation="jobSalary"]')?.textContent;

    // get job sub category from data-automation="jobSubClassification"
    let job_sub_category = article.querySelector('[data-automation="jobSubClassification"]')?.textContent;

    // get job category from data-automation="jobClassification"
    let job_category = article.querySelector('[data-automation="jobClassification"]')?.textContent;

    // get job desc 1, 2 , 3 from ul li in article, and put into 3 var
    var job_desc_ele_list = article.querySelectorAll("ul li");
    let job_desc_1 = job_desc_ele_list?.[0]?.textContent;
    let job_desc_2 = job_desc_ele_list?.[1]?.textContent;
    let job_desc_3 = job_desc_ele_list?.[2]?.textContent;

    //get text from data-automation="jobListingDate"
    let job_listing_date = article.querySelector('[data-automation="jobListingDate"]')?.textContent;

    //text cloud looks like "4m ago", "23h ago", "4d ago", calculate the listing datetime
    let post_at = calculate_datetime(job_listing_date);

    let job = {
      job_id,
      job_id_text,
      job_title,
      job_link,
      company_name,
      company_link,
      location_1,
      location_2,
      salary,
      job_sub_category,
      job_category,
      job_desc_1,
      job_desc_2,
      job_desc_3,
      post_at,
    };
    jobs.push(job);
  }

  // loop job and fetch detail
  let job_detail_promise_list = [];
  for (let i = 0; i < jobs.length; i++) {
    let job_detail_promise = (async () => {
      let url = "https://hk.jobsdb.com" + jobs[i].job_link;
      let [job_detail_html, contact] = await fetch_job_detail(url);
      jobs[i].job_detail_html = job_detail_html;
      jobs[i].contact = contact;
      jobs[i].job_detail_html_fetched = job_detail_html ? true : false;
    })();
    job_detail_promise_list.push(job_detail_promise);
    await delay(100);
  }

  // await job_detail_promise_list
  await Promise.all(job_detail_promise_list);

  return jobs;
}
async function fetch_job_detail(url) {
  let response = await fetch(url);
  let html_string = await response.text();

  // try two time
  if (response.status != 200) {
    response = await fetch(url);
    if (response.status != 200) {
      return [null, null];
    }
  }

  let dom = new JSDOM(html_string);
  let job_detail_ele = dom.window.document.querySelector('[data-automation="jobAdDetails"]');
  let job_detail_html = job_detail_ele?.innerHTML;

  let contact = extract_contact(job_detail_ele);

  return [job_detail_html, contact];
}
async function fetch_job_list(max_fetch_page, last_job_id) {
  let full_job_list = [];
  for (let page = 1; page <= max_fetch_page; page++) {
    console.log("fetching page " + page);

    let url = `https://hk.jobsdb.com/jobs-in-information-communication-technology?page=${page}&sortmode=ListedDate`;
    let response = await fetch(url);
    if (response.status != 200) {
      console.log("fetching page " + page + " failed, status:" + response.status);
      break;
    }

    let html_string = await response.text();
    let jobs_list = await extract_job_list(html_string);
    full_job_list = full_job_list.concat(jobs_list);

    // if jobs list included last_job_id, break
    let existed_job = jobs_list.find((job) => job.job_id === last_job_id);
    if (existed_job) {
      console.log("stop at page " + page + ", job_id exsited - " + existed_job.job_id);
      break;
    }
  }
  return full_job_list;
}
async function get_last_job_id(mongo_col) {
  let result = await mongo_col.find({}).sort({ job_id: -1 }).limit(1);
  let docs = await result.toArray();
  let last_job_id = docs?.[0]?.job_id;
  return last_job_id || 0;
}
async function get_exsited_job_id_list(jobs, mongo_col) {
  let job_id_array = jobs.map((job) => job.job_id);
  let result = mongo_col.find({ job_id: { $in: job_id_array } }).project({ job_id: 1, _id: 0 });
  let exsited_job_list = await result.toArray();
  let exsited_job_id_list = exsited_job_list.map((j) => j.job_id);
  return exsited_job_id_list;
}
(async () => {
  console.time("executed_time");
  console.log("start at " + get_now());

  try {
    var [mongo_client, mongo_db, mongo_col] = await init_mongo_client();
    let last_job_id = await get_last_job_id(mongo_col);
    console.log("last_job_id: " + last_job_id);

    let max_fetch_page = process.env.MAX_FETCH_PAGE || 10;
    console.log("max_fetch_page: " + max_fetch_page);

    let jobs = await fetch_job_list(max_fetch_page, last_job_id);
    console.log("fetched jobs length: " + jobs.length);

    if (jobs.length == 0) {
      console.log("no new jobs, exit");
      return;
    }

    let exsited_job_id_list = await get_exsited_job_id_list(jobs, mongo_col);
    jobs = jobs.filter((job) => !exsited_job_id_list.includes(job.job_id));
    console.log("filtered jobs length: " + jobs.length);

    if (jobs.length == 0) {
      console.log("no new jobs, exit");
      return;
    }

    let reversed_jobs = jobs.reverse();

    let insert_result = await mongo_col.insertMany(reversed_jobs, { ordered: true });
    console.log(`${insert_result.upsertedCount} documents were inserted`);
  } finally {
    console.log("close mongo client");
    await mongo_client.close();
  }
  console.log("end at " + get_now());
  console.timeEnd("executed_time");
})();