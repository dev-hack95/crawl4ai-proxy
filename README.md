# Crawl4AI Proxy

A lightweight FastAPI proxy service for submitting URLs to a [Crawl4AI](https://github.com/unclecode/crawl4ai) instance and retrieving crawled Markdown content.

The project consists of two Docker services:

* **Crawl4AI** — performs the actual web crawling.
* **Crawl4AI Proxy** — exposes a simple HTTP API on port `8087` and forwards crawl requests to Crawl4AI.

## Architecture

```text
                 ┌─────────────────────┐
                 │       Client        │
                 │                     │
                 │  POST /search       │
                 └──────────┬──────────┘
                            │
                       :8087│
                            ▼
                 ┌─────────────────────┐
                 │  crawl4ai-proxy     │
                 │     FastAPI         │
                 │                     │
                 │     /search         │
                 └──────────┬──────────┘
                            │
                            │ HTTP
                            ▼
                 ┌─────────────────────┐
                 │      Crawl4AI       │
                 │                     │
                 │      :11235         │
                 │                     │
                 │       /md           │
                 └─────────────────────┘
```

## Project Structure

```text
.
├── Dockerfile
├── docker-compose.yml
├── main.py
├── requirements.txt
└── schema.sql
```

The `__pycache__` directory is generated automatically by Python and does not need to be committed to version control.

## Requirements

You need:

* Docker
* Docker Compose
* A machine capable of running the Crawl4AI image
* Network access to the URLs you want to crawl

If you are running the services on an ARM64 machine, make sure the `crawl4ai-proxy:arm64` image is built for the appropriate architecture.

## Docker Compose

The recommended way to run the complete stack is with Docker Compose.

Example `docker-compose.yml`:

```yaml
version: "3.8"

services:
  crawl4ai:
    image: unclecode/crawl4ai:latest
    container_name: crawl4ai
    ports:
      - "11235:11235"
    shm_size: 1g
    restart: unless-stopped

  crawl4ai-proxy:
    image: crawl4ai-proxy:arm64
    container_name: crawl4ai-proxy
    ports:
      - "8087:8087"
    environment:
      - CRAWL4AI_URL=http://crawl4ai:11235/md
    depends_on:
      - crawl4ai
    restart: unless-stopped
```

### Start the services

```bash
docker compose up -d
```

Check the running containers:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f crawl4ai-proxy
```

To stop the stack:

```bash
docker compose down
```

## Building the Proxy Image

If the `crawl4ai-proxy:arm64` image does not already exist locally, build it:

```bash
docker build -t crawl4ai-proxy:arm64 .
```

Then start the Compose stack:

```bash
docker compose up -d
```

## Configuration

The proxy uses environment variables to configure its connection to Crawl4AI.

### `CRAWL4AI_URL`

The URL of the Crawl4AI Markdown endpoint.

When using Docker Compose, the proxy should communicate with Crawl4AI using the Docker service name:

```text
http://crawl4ai:11235/md
```

For example:

```yaml
environment:
  - CRAWL4AI_URL=http://crawl4ai:11235/md
```

When running the proxy outside Docker, you can instead point it at the host/IP address where Crawl4AI is available:

```bash
CRAWL4AI_URL=http://192.168.1.2:11235/md
```

### `PROXY_API_KEY`

Optional API key configuration:

```bash
PROXY_API_KEY=
```

If authentication is implemented/enforced by `main.py`, configure the value through the environment rather than hard-coding it in the source code.

## API

The proxy exposes the following endpoint:

```text
POST /search
```

### Request

The request body is JSON and contains a list of URLs:

```json
{
  "urls": [
    "https://dev.to/jimmyyeung/upgrade-to-django-5-with-psycopg3-4e8b"
  ]
}
```

### cURL Example

With the proxy running on `192.168.1.13`:

```bash
curl --request POST \
  --url http://192.168.1.13:8087/search \
  --header 'Content-Type: application/json' \
  --data '{
    "urls": [
      "https://dev.to/jimmyyeung/upgrade-to-django-5-with-psycopg3-4e8b"
    ]
  }'
```

If you are testing locally:

```bash
curl --request POST \
  --url http://localhost:8087/search \
  --header 'Content-Type: application/json' \
  --data '{
    "urls": [
      "https://dev.to/jimmyyeung/upgrade-to-django-5-with-psycopg3-4e8b"
    ]
  }'
```

## Multiple URLs

Multiple URLs can be submitted in the same request:

```json
{
  "urls": [
    "https://example.com",
    "https://example.org",
    "https://dev.to/jimmyyeung/upgrade-to-django-5-with-psycopg3-4e8b"
  ]
}
```

Example:

```bash
curl --request POST \
  --url http://localhost:8087/search \
  --header 'Content-Type: application/json' \
  --data '{
    "urls": [
      "https://example.com",
      "https://example.org"
    ]
  }'
```

## Running Without Docker

The proxy can also be run directly with Python.

Create a virtual environment:

```bash
python3.12 -m venv .venv
```

Activate it:

### Linux/macOS

```bash
source .venv/bin/activate
```

### Windows

```powershell
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure Crawl4AI:

```bash
export CRAWL4AI_URL=http://192.168.1.2:11235/md
```

Run the API:

```bash
uvicorn main:app --host 0.0.0.0 --port 8087
```

The API will then be available at:

```text
http://localhost:8087
```

## Dockerfile

The proxy image is based on Python 3.12:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV CRAWL4AI_URL=http://192.168.1.2:11235/md

ENV PROXY_API_KEY=

EXPOSE 8087

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8087"]
```

### Important Docker Networking Note

When the proxy runs inside the same Docker Compose network as Crawl4AI, prefer:

```text
http://crawl4ai:11235/md
```

instead of:

```text
http://192.168.1.2:11235/md
```

Docker Compose automatically provides DNS resolution for the service name `crawl4ai`.

## Database Schema

The project includes `schema.sql` containing the crawler data table.

```sql
CREATE TABLE IF NOT EXISTS crawler_data (
    id              bigserial PRIMARY KEY,
    url             character varying(2048),
    url_hash        character varying(64),
    content_type    character varying(255),
    data            text,
    crawl_timestamp timestamp with time zone,
    last_updated    timestamp with time zone,
    last_accessed   timestamp with time zone,
    created_at      timestamp with time zone
);
```

### Columns

| Column            | Description                                             |
| ----------------- | ------------------------------------------------------- |
| `id`              | Unique database identifier                              |
| `url`             | Original URL that was crawled                           |
| `url_hash`        | Hash of the URL, useful for deduplication/cache lookups |
| `content_type`    | Type of content returned by the crawler                 |
| `data`            | Crawled content                                         |
| `crawl_timestamp` | Time at which the URL was crawled                       |
| `last_updated`    | Time the stored content was last updated                |
| `last_accessed`   | Time the stored content was last requested              |
| `created_at`      | Time the database record was created                    |

## Health Checks and Troubleshooting

### Check the proxy

```bash
curl http://localhost:8087
```

If `main.py` exposes a health endpoint, use the appropriate endpoint defined there, for example:

```bash
curl http://localhost:8087/health
```

### Check Crawl4AI

Verify that the Crawl4AI container is running:

```bash
docker ps
```

You should see:

```text
crawl4ai
crawl4ai-proxy
```

Check its logs:

```bash
docker logs crawl4ai
```

### Check proxy logs

```bash
docker logs crawl4ai-proxy
```

Or with Compose:

```bash
docker compose logs -f crawl4ai-proxy
```

### Test connectivity from the proxy container

If the proxy cannot connect to Crawl4AI, enter the container:

```bash
docker exec -it crawl4ai-proxy sh
```

Then test the Crawl4AI service:

```bash
wget -O- http://crawl4ai:11235/md
```

The exact response depends on the Crawl4AI endpoint and request format implemented by the proxy.

## Common Issues

### `Connection refused`

If the proxy reports that it cannot connect to Crawl4AI, verify:

1. The Crawl4AI container is running.
2. Crawl4AI is listening on port `11235`.
3. Both containers are on the same Docker network.
4. `CRAWL4AI_URL` uses `crawl4ai` as the hostname when running through Compose.

Correct:

```text
http://crawl4ai:11235/md
```

Potentially incorrect from inside the container:

```text
http://localhost:11235/md
```

`localhost` inside `crawl4ai-proxy` refers to the proxy container itself, not the Crawl4AI container.

### Proxy is reachable but crawling fails

Check:

```bash
docker compose logs crawl4ai
docker compose logs crawl4ai-proxy
```

Also verify that the target URL is publicly accessible from the Docker container.

### Port already in use

If port `8087` is already occupied, change the host-side port:

```yaml
ports:
  - "8088:8087"
```

The proxy will remain on port `8087` inside the container, while clients connect to:

```text
http://localhost:8088
```

Similarly, the Crawl4AI port can be remapped if required.

## Security

The proxy should generally **not** be exposed directly to the public internet without authentication and appropriate network controls.

Recommended practices:

* Set a strong `PROXY_API_KEY` if API-key authentication is supported by the application.
* Restrict access to port `8087` using firewall rules.
* Put the service behind a reverse proxy when public access is required.
* Avoid exposing Crawl4AI's `11235` port publicly unless necessary.
* Validate and limit submitted URLs to prevent abuse.
* Consider request timeouts and maximum URL counts for `/search`.

## Production Considerations

For production deployments, consider adding:

* API authentication
* Request rate limiting
* URL validation
* Maximum URL batch size
* Crawl timeouts
* Structured logging
* Health checks in Docker Compose
* Persistent database storage
* Database indexes on `url_hash`
* HTTPS through a reverse proxy
* Resource limits for Crawl4AI
* Monitoring and metrics

A useful index for URL lookups would be:

```sql
CREATE INDEX IF NOT EXISTS idx_crawler_data_url_hash
    ON crawler_data (url_hash);
```

If each URL should only have one cached record, a unique index may be more appropriate:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_crawler_data_url_hash_unique
    ON crawler_data (url_hash);
```

Use the unique version only if the application logic expects one record per URL.

## Development

Run the proxy locally:

```bash
uvicorn main:app --host 0.0.0.0 --port 8087 --reload
```

The `--reload` option is useful during development because Uvicorn automatically reloads the application when source files change.

