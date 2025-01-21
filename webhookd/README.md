# Webhook daemon for Omada controller

Current daemon is accepting connections from Omada controller using http://localhost:8080/tg_msg and sends the content to Telegram Bot Chat

Python script can be executed either in background or foreground

Background use - daemon will redirect outputs to `stdout.log` and `stderr.log` files under the directory specified by `log_dir` option from `config.json` configuration file.
    `python webhookd.py`

Foreground use - output will be shown in current console and script will not go to background.
    `python webhookd.py --fg`
