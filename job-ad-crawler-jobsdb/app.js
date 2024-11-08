const jsdom = require("jsdom");
const { JSDOM } = jsdom;
// const { data_helper } = require("./data_helper_mongo");
const { data_helper } = require("./data_helper_sqlite");
const { logger } = require("./logger_helper");

const http_headers = {
  accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
  "accept-language": "zh-TW,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,zh-HK;q=0.5",
  "cache-control": "max-age=0",
  priority: "u=0, i",
  "sec-ch-ua": '"Chromium";v="130", "Microsoft Edge";v="130", "Not?A_Brand";v="99"',
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": '"Windows"',
  "sec-fetch-dest": "document",
  "sec-fetch-mode": "navigate",
  "sec-fetch-site": "same-origin",
  "sec-fetch-user": "?1",
  "upgrade-insecure-requests": "1",
};

const fetch_options = {
  headers: http_headers,
  referrerPolicy: "no-referrer-when-downgrade",
  body: null,
  method: "GET",
  mode: "cors",
  credentials: "include",
};

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
function get_now(include_time = true) {
  let now = new Date();
  let iso = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString();
  if (include_time) {
    return iso.replace(/[TZ]/g, " ");
  } else {
    return iso.substring(0, 10);
  }
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
  // var href = "/cdn-cgi/l/email-protection#67060b0b02094917080809270a06091708100215001504490f0c";
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
  if (!process.env.OUTPUT_FOLDER) logger.warn("env var OUTPUT_FOLDER is not defined");
  let path = process.env.OUTPUT_FOLDER;
  try {
    let fs = require("fs").promises;
    let json_string = JSON.stringify(jobs, null, 2);
    await fs.writeFile(`${path}jobsdb_${get_now()}.json`, json_string, "utf-8");
  } catch (error) {}
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

  return jobs;
}
async function fetch_job_detail(url) {
  let response = await fetch(url, fetch_options);
  let html_string = await response.text();

  // try two time
  if (response.status != 200) {
    response = await fetch(url, fetch_options);
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
    logger.info("fetching page " + page);

    let url = `https://hk.jobsdb.com/jobs-in-information-communication-technology?page=${page}&sortmode=ListedDate`;
    let response = await fetch(url, fetch_options);
    if (response.status != 200) {
      logger.info("fetching page " + page + " failed, status:" + response.status);
      break;
    }

    let html_string = await response.text();
    let jobs_list = await extract_job_list(html_string);
    full_job_list = full_job_list.concat(jobs_list);

    // if jobs list included last_job_id, break
    let existed_job = jobs_list.find((job) => job.job_id === last_job_id);
    if (existed_job) {
      logger.info("stop at page " + page + ", job_id exsited - " + existed_job.job_id);
      // break;
    }
  }
  return full_job_list;
}

async function fetch_job_list_detail(jobs) {
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
    await delay(process.env.DELAY_BETWEEN_FETCH_DETAIL || 1000);
  }

  // await job_detail_promise_list
  await Promise.all(job_detail_promise_list);
  return jobs;
}

function split_array(arr, size) {
  const result = [];
  for (let i = 0; i < arr.length; i += size) {
    result.push(arr.slice(i, i + size));
  }
  return result;
}

(async function main() {
  let start_ms = performance.now();
  logger.info("start at " + get_now());
  logger.info("APP_ENV: " + process.env.APP_ENV);

  try {
    await data_helper.init_db_client();

    let last_job_id = await data_helper.get_last_job_id();
    logger.info("last_job_id: " + last_job_id);

    let max_fetch_page = process.env.MAX_FETCH_PAGE || 10;
    logger.info("max_fetch_page: " + max_fetch_page);

    let fetched_jobs = await fetch_job_list(max_fetch_page, last_job_id);
    logger.info("fetched jobs length: " + fetched_jobs.length);

    let existed_job_id_list = await data_helper.get_existed_job_id_list(fetched_jobs);

    let new_jobs = fetched_jobs.filter((job) => existed_job_id_list.includes(job.job_id) == false);
    logger.info("new jobs length: " + new_jobs.length);
    if (new_jobs.length == 0) {
      return;
    }

    let new_jobs_with_detail = await fetch_job_list_detail(new_jobs);
    logger.info("fetched all detail");

    logger.info("reverse jobs list");
    let reversed_jobs = new_jobs_with_detail.reverse();

    logger.info("save jobs to file");
    await save_jobs_to_file(reversed_jobs);

    logger.info("insert many into database");

    const MAX_INSERT_SIZE = 30;
    const inserted = 0;
    split_array(reversed_jobs, MAX_INSERT_SIZE).forEach(async (jobs) => {
      inserted += await data_helper.insert_many(jobs);
    });
    
    logger.info(`${inserted} jobs were inserted`);
  } catch (error) {
    logger.error("program error", error);
  } finally {
    logger.info("close database client");
    await data_helper?.close();
    let during_s = ((performance.now() - start_ms) / 1000).toFixed(2);
    logger.info("end at " + get_now() + ", during " + during_s + "s");
    logger.info("----------------------------------------");
  }
})();
