> **Community source release (MIT).** Self-host using your own credentials. No NabuxAI production accounts or hosted-service access are included.

# YouTube MCP by Nabux

Multi-user YouTube MCP Gateway using Google's official YouTube Data API v3 and YouTube Analytics API.

Production target: `https://youtube.nabuxai.com`  
MCP: `https://youtube.nabuxai.com/mcp`  
OAuth callback: `https://youtube.nabuxai.com/youtube/callback`

## Tools

- `youtube_accounts`
- `youtube_channel`
- `youtube_list_videos`
- `youtube_get_video`
- `youtube_upload_video`
- `youtube_update_video`
- `youtube_comments`
- `youtube_reply_comment`
- `youtube_moderate_comment`
- `youtube_playlists`
- `youtube_create_playlist`
- `youtube_add_to_playlist`
- `youtube_analytics`

## Upload architecture

`youtube_upload_video` accepts a public HTTPS media URL. The gateway streams it to temporary disk with a configurable size limit and then uses YouTube's official resumable `videos.insert` upload flow in chunks. Temporary files are deleted after upload.

Default privacy is `private`. Google may additionally restrict uploads from unverified API projects to private until the API project passes the required compliance audit.

The uploader supports official metadata including title, description, tags, category, made-for-kids status and `containsSyntheticMedia`.

## OAuth / security

Google OAuth uses Authorization Code + PKCE and requests offline access so a refresh token can be stored. Access and refresh tokens are encrypted at rest; MCP bearer tokens are hashed and separate from Google credentials.

Default scopes:

```text
https://www.googleapis.com/auth/youtube.readonly
https://www.googleapis.com/auth/youtube.upload
https://www.googleapis.com/auth/youtube.force-ssl
https://www.googleapis.com/auth/yt-analytics.readonly
```

For a public production app, configure the Google OAuth consent screen and complete any verification required for the requested scopes.

## Coolify

Deploy `feature/youtube-mcp-gateway` using `docker-compose.coolify.yml` at `youtube.nabuxai.com`, port 8000, with persistent `/data`.

Required variables:

```text
PUBLIC_BASE_URL=https://youtube.nabuxai.com
APP_SECRET_KEY=<32+ random chars>
GOOGLE_CLIENT_ID=<OAuth web client ID>
GOOGLE_CLIENT_SECRET=<OAuth client secret>
GOOGLE_REDIRECT_URI=https://youtube.nabuxai.com/youtube/callback
INTERNAL_SERVICE_TOKEN=<random server-to-server secret>
```

Also enable **YouTube Data API v3** and **YouTube Analytics API** in the same Google Cloud project.

## NabuGen API

```text
GET  /internal/v1/accounts/{account_key}
POST /internal/v1/accounts/{account_key}/upload
```

The upload endpoint uses the same official resumable path as the MCP tool.

## Status

Code is deployment-shaped and CI-tested. Real E2E upload/analytics requires Google credentials, enabled APIs, OAuth consent/verification as applicable, HTTPS, and an authorized YouTube channel.
