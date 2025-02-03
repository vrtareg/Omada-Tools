# Omada-Tools
Various TP-Link Omada related samples and useful scripts

# WebHook daemon
As per https://www.reddit.com/r/TPLink_Omada/comments/1i395zr/omada_monitoring_script/ I created Python based daemon which is using fastAPI and uvicorn to act as a middleware between the Omada Controller and Telegram Bot or Discord channel.

Webhook can be used in Omada controller to send various messages to desired Telegram Chat or Discord channel.

Telegram Bot can be created using the BotFather and then chat ID can be determined using https://core.telegram.org/bots/api#getme and API token

Discord Bot can be created using Discord Developer Portal https://discord.com/developers/applications by creating Application, Bot for Bot Token.
OAuth2 invite needs to be created to invite bot to Server then channel ID required for configuration.
