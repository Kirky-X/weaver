## 1. Configuration

- [x] 1.1 Add `PipelineUrlEndpointSettings` class to `src/config/settings.py` with `whitelist_enabled` and `allowed_domains` fields
- [x] 1.2 Add `pipeline_url_endpoint` field to main `Settings` class

## 2. API Endpoint

- [x] 2.1 Add `ProcessUrlRequest` and `ProcessUrlResponse` Pydantic models to `src/api/endpoints/pipeline.py`
- [x] 2.2 Implement `POST /pipeline/url` endpoint with URL validation, task creation, and background task launch
- [x] 2.3 Add whitelist domain validation logic when `whitelist_mode=true`

## 3. Background Processing

- [x] 3.1 Implement `process_single_url()` async function for background URL processing
- [x] 3.2 Add task status update logic (queued → running → completed/failed)
- [x] 3.3 Wire Crawler and Pipeline calls within the background task

## 4. Error Handling

- [x] 4.1 Add error response codes for URL validation failures (SSRF, whitelist, format)
- [x] 4.2 Handle FetchError from crawler with proper task status update

## 5. Testing

- [x] 5.1 Write unit tests for URL validation (SSRF blocking, whitelist mode)
- [x] 5.2 Write integration tests for `/pipeline/url` endpoint
- [x] 5.3 Verify task status query compatibility with existing `/pipeline/tasks/{task_id}`