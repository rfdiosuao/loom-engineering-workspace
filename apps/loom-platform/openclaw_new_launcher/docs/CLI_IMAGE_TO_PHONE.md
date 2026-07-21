# OpenClaw Image-To-Phone CLI

This CLI connects the launcher-side image workflow with APKClaw's phone gallery import API.

It can:

- generate an AI image from a prompt;
- save the result under `data/generated-images/`;
- upload the image to APKClaw through the signed launcher channel `POST /api/lumi/media/import_image`;
- make the result appear in the phone gallery under the configured album, defaulting to `Pictures/OpenClaw`.

## Command

```powershell
npm run phone:image -- --prompt "a clean product logo, cyan and gold, app icon style" `
  --image-base-url https://api.example.com `
  --image-api-key sk-xxx `
  --phone-url http://192.168.1.137:9527 `
  --phone-token 66666666
```

The image API is OpenAI-compatible. If the base URL ends with `/v1`, the CLI calls:

```text
<baseUrl>/images/generations
```

Otherwise it calls:

```text
<baseUrl>/v1/images/generations
```

## Upload Existing Image

```powershell
npm run phone:image -- --image .\logo_256.png `
  --phone-url http://192.168.1.137:9527 `
  --phone-token 66666666 `
  --filename openclaw-cli-test.png
```

## Verified Phone Smoke Test

Validated against APKClaw `6.21` / `versionCode=810` on `2026-05-11`:

```powershell
npm run phone:image -- --image .\logo_256.png `
  --phone-url http://192.168.1.137:9527 `
  --phone-token 66666666 `
  --filename openclaw-cli-upload-test.png `
  --json
```

Expected phone-side result:

```text
Pictures/OpenClaw/openclaw-cli-upload-test.png
```

The CLI pairs with `/api/lumi/security/pair`, signs the upload request, and returns a MediaStore URI under `Pictures/OpenClaw`.

## Environment Variables

```powershell
$env:OPENCLAW_IMAGE_BASE_URL="https://api.example.com"
$env:OPENCLAW_IMAGE_API_KEY="sk-xxx"
$env:OPENCLAW_IMAGE_MODEL="gpt-image-2"
$env:OPENCLAW_PHONE_BASE_URL="http://192.168.1.137:9527"
$env:OPENCLAW_PHONE_TOKEN="66666666"
```

Then run:

```powershell
npm run phone:image -- --prompt "a cinematic product photo of a silver portable SSD"
```

## Config Fallback

The CLI also reads image API settings from:

```text
imgapi_config.json
```

with this shape:

```json
{
  "baseUrl": "https://api.example.com",
  "apiKey": "sk-xxx"
}
```

Do not commit real API keys or phone tokens.

## Useful Options

| Option | Purpose |
| --- | --- |
| `--prompt` | AI image prompt |
| `--image` | Upload an existing image instead of generating |
| `--size` | Image size, default `1024x1024` |
| `--count` | Number of images, default `1`, max `4` |
| `--album` | Phone gallery album, default `OpenClaw` |
| `--filename` | Phone-side filename when uploading one image |
| `--no-upload` | Generate locally only |
| `--json` | Print machine-readable JSON |
