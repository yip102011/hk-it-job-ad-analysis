const winston = require("winston");
const app_name = require(`${__dirname}/package.json`).name;
const log_folder = process.env.OUTPUT_LOG_FOLDER;

function get_now(include_time = true) {
  let now = new Date();
  let iso = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString();
  if (include_time) {
    return iso.replace("T", " ").replace("Z", "");
  } else {
    return iso.substring(0, 10);
  }
}

const logger = winston.createLogger();

logger.add(new winston.transports.File({ filename: log_folder + "sturctured.log" }));

let format = winston.format.combine(
  winston.format.printf((info) => {
    let level_str = `[${info.level.toUpperCase()}]`.padEnd(7, " ");
    let message = info.message;
    return `${get_now()}, ${level_str}, ${app_name}, ${message}`;
  })
);
logger.add(new winston.transports.File({ format: format, filename: log_folder + "error.log", level: "error" }));
logger.add(new winston.transports.File({ format: format, filename: log_folder + "trace.log" }));
logger.add(new winston.transports.Console({ format: format }));

exports.logger = logger;
