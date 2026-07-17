# Fast Receipt Image Preprocessing Design

## Goal

Improve difficult receipt photos before Splitik sends them to the configured vision model, without GPU requirements, extra model calls, or dataset evaluation.

## Constraints

- The normal path must still make exactly one vision-model request.
- Processing must use CPU-only Pillow operations; OpenCV and GPU runtimes are out of scope.
- The original upload must always remain unchanged and recoverable.
- Dataset and live-provider quality evaluation are out of scope. Verification uses synthetic image fixtures and existing backend tests only.
- Private storage keys and generated URLs must not appear in public API responses or interaction logs.
- Processing failures must fall back to the original image rather than failing the upload.

## Architecture

Add a focused `receipt_image_preprocessing` service called during Splitik attachment upload. It validates decoded pixel dimensions, applies EXIF orientation, computes inexpensive luminance/contrast/sharpness signals, and decides whether a model-ready derivative is useful.

Every oversized or EXIF-rotated image receives a normalized derivative. Dark or low-contrast images additionally receive a conservative contrast/brightness enhancement. Normal images remain unchanged, so their original URL is used by the vision model.

The attachment document stores only safe processing metadata plus a private derivative location. Public serialization removes both original and derivative storage details. `image_urls_for_actor` produces one URL per attachment: the derivative when present, otherwise the original. Splitik therefore keeps the existing single vision request.

## Processing Policy

- Reject decoded images above a configurable pixel ceiling before expensive work.
- Apply `ImageOps.exif_transpose`.
- Resize proportionally when the longest side exceeds the configured model-input limit.
- Measure grayscale mean and standard deviation for brightness and contrast.
- Measure edge variance as a cheap sharpness diagnostic; blur is reported but not sharpened aggressively.
- Apply conservative autocontrast and brightness correction only when thresholds classify the image as dark or low contrast.
- Encode derivatives in JPEG with bounded quality, except transparency-bearing PNG/WebP images, which remain PNG.
- If decoding or derivative storage fails, store and use the original image and record a safe failure status.

## Storage and Privacy

For S3-backed uploads, originals keep the existing attachment key and derivatives use a sibling private key. For Mongo-backed development uploads, derivative bytes may be stored inside the private attachment document. Public metadata exposes only a processing summary such as status, selected variant, dimensions, and quality flags.

Deleting an attachment must delete both objects when a derivative exists. No bucket name, key, bytes, presigned URL, or detailed exception is returned to the client or persisted in Splitik interaction logs.

## Observability

Add Prometheus counters for preprocessing outcomes and a histogram for CPU duration. Labels remain low-cardinality: outcome and selected variant only. Attachment metadata records processing duration, dimensions, and quality flags for debugging.

## Tests

Synthetic in-memory images cover unchanged normal images, EXIF rotation, proportional resizing, low-contrast enhancement, pixel-limit fallback, preservation of originals, derivative selection, derivative deletion, storage privacy, and the invariant that one attachment still creates one vision URL and one model request.

No receipt dataset, benchmark repository, or live model provider is used.
