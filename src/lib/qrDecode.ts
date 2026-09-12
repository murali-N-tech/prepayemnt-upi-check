/**
 * Reading a UPI QR code out of a camera frame or a photo.
 *
 * Why this is done on the device
 * -----------------------------
 * The page used to ask the user to paste "the QR code's contents" — a string
 * like `upi://pay?pa=...` that nobody has, because what a person actually has
 * in front of them is a QR code on a shop counter. Decoding it here closes
 * that gap, and doing it on the device rather than on the server means:
 *
 *   - the photo never leaves the phone, which matters when the picture may
 *     also contain a shopfront, a bill, or somebody's face;
 *   - live camera scanning is possible at all (a round trip per frame is not);
 *   - no new native dependency — pyzbar needs the zbar DLL, which is a fight
 *     on Windows and on Render.
 *
 * The decoded string is then sent to /api/payee/check exactly as if it had
 * been pasted, so there is still one implementation of the actual analysis.
 *
 * SECURITY: the decoded string is untrusted input from a physical object that
 * anyone could have printed and stuck on a wall. It is never opened, followed,
 * or rendered as a link — it is displayed as plain monospace text and passed to
 * the backend check. A QR that turns out not to be a UPI link is not an error
 * to swallow either: `parse_upi_target` raises `not_a_payment_link` at critical
 * severity for exactly that case, which is one of the things this project
 * exists to catch. So anything that decodes gets sent.
 */

export interface QrHit {
  /** The raw decoded string. Untrusted. */
  text: string;
  /** Which attempt found it — useful when telling the user why a photo failed. */
  via: string;
  /** Corner points, when the decoder gives them, for drawing an overlay. */
  corners?: { x: number; y: number }[];
}

type JsQrModule = typeof import("jsqr");

let jsQrPromise: Promise<JsQrModule["default"] | null> | null = null;

/**
 * jsQR is loaded lazily. It is only needed when BarcodeDetector is missing or
 * when a still image needs the multi-pass treatment, and keeping it out of the
 * initial bundle keeps the rest of the app's first load unchanged.
 */
async function getJsQr() {
  if (!jsQrPromise) {
    jsQrPromise = import("jsqr")
      .then((m) => m.default)
      .catch(() => null);
  }
  return jsQrPromise;
}

/** Chrome and the Android WebView have this natively; Firefox and Safari do not. */
function nativeDetector(): any | null {
  const BD = (globalThis as any).BarcodeDetector;
  if (!BD) return null;
  try {
    return new BD({ formats: ["qr_code"] });
  } catch {
    return null;
  }
}

let nativeDetectorInstance: any | null | undefined;

function detector() {
  if (nativeDetectorInstance === undefined) nativeDetectorInstance = nativeDetector();
  return nativeDetectorInstance;
}

export function hasNativeDetector(): boolean {
  return detector() !== null;
}

/* ── Camera frames ─────────────────────────────────────────────────────────── */

/**
 * One decode attempt against a live video frame. Deliberately cheap: this runs
 * many times a second, so it does the single fastest thing that works and
 * leaves the expensive multi-pass work to still images.
 */
export async function decodeFromVideo(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement
): Promise<QrHit | null> {
  if (!video.videoWidth || !video.videoHeight) return null;

  const native = detector();
  if (native) {
    try {
      const found = await native.detect(video);
      if (found?.length) {
        return {
          text: found[0].rawValue,
          via: "camera (native detector)",
          corners: found[0].cornerPoints?.map((p: any) => ({ x: p.x, y: p.y })),
        };
      }
      return null;
    } catch {
      // Fall through to jsQR — some WebViews expose the constructor but throw
      // on detect().
      nativeDetectorInstance = null;
    }
  }

  const jsQR = await getJsQr();
  if (!jsQR) return null;

  // Downscale before decoding. A 1080p frame is ~2M pixels and jsQR is pure
  // JS: at full resolution it cannot keep up with the frame rate, and the
  // scanner feels broken rather than slow.
  const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
  const w = Math.round(video.videoWidth * scale);
  const h = Math.round(video.videoHeight * scale);
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h);
  const hit = jsQR(data.data, w, h, { inversionAttempts: "attemptBoth" });
  if (!hit) return null;
  return {
    text: hit.data,
    via: "camera",
    corners: [
      hit.location.topLeftCorner,
      hit.location.topRightCorner,
      hit.location.bottomRightCorner,
      hit.location.bottomLeftCorner,
    ].map((p) => ({ x: p.x / scale, y: p.y / scale })),
  };
}

/* ── Still images ──────────────────────────────────────────────────────────── */

interface Pass {
  name: string;
  /** Longest edge to resize to, or null to keep the natural size. */
  size: number | null;
  /** Push mid-greys apart — recovers a washed-out photo. */
  contrast: boolean;
}

/**
 * A photo of a QR code is nothing like a screenshot of one: skewed, softly
 * focused, unevenly lit, and the code may be a small part of a large frame.
 * These passes run in order until one succeeds, cheapest and most likely
 * first, so the common case costs one pass.
 *
 * Each pass here was kept because a test image needed it. See the note below
 * the list for the ones that were removed.
 */
const PASSES: Pass[] = [
  // Normalising the size first does double duty: a 12-megapixel photo decodes
  // in a fraction of the time (measured: 973ms at 4000x3000 against ~90ms
  // resized), and a small screenshot crop is scaled UP, which genuinely helps
  // because the decoder needs several pixels per QR module to find the corner
  // patterns.
  { name: "resized", size: 1400, contrast: false },
  // In case resampling destroyed a marginal code that the raw pixels carry.
  { name: "as taken", size: null, contrast: false },
  // Earns its place: a washed-out photo (contrast 0.28x of normal) failed
  // every other pass and decoded on this one.
  { name: "contrast boosted", size: 1400, contrast: true },
  { name: "enlarged + contrast", size: 2200, contrast: true },
];

// There are deliberately NO rotation passes. QR finder patterns are
// rotation-invariant, so the decoder reads a code at any angle by design -
// verified against images rotated 90/180/270 degrees and photographed at a
// steep perspective angle, all of which decoded on the first pass. Four
// rotation passes were written first and removed once measurement showed they
// never fired: they only made every genuine failure four passes slower.
//
// What cannot be recovered is a code with too few pixels per module. A 60px QR
// fails every pass and always will - the information is not in the image - so
// the failure message asks the user to fill more of the frame rather than
// suggesting another attempt.

function boostContrast(d: ImageData): void {
  const px = d.data;
  // Mean luminance as the pivot, then push each pixel away from it. A fixed
  // pivot of 128 blows out a photo taken in shade.
  let sum = 0;
  for (let i = 0; i < px.length; i += 4) {
    sum += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
  }
  const mean = sum / (px.length / 4);
  const gain = 2.2;
  for (let i = 0; i < px.length; i += 4) {
    const lum = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2];
    const out = Math.max(0, Math.min(255, (lum - mean) * gain + mean));
    px[i] = px[i + 1] = px[i + 2] = out;
  }
}

function draw(
  source: CanvasImageSource,
  naturalW: number,
  naturalH: number,
  pass: Pass
): ImageData | null {
  // Cap the upscale at 4x. Beyond that there is no more information in the
  // image, only a bigger buffer to scan.
  const scale = pass.size ? Math.min(pass.size / Math.max(naturalW, naturalH), 4) : 1;
  const w = Math.max(1, Math.round(naturalW * scale));
  const h = Math.max(1, Math.round(naturalH * scale));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;

  // White, not transparent: a transparent PNG decodes as black-on-black.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(source, 0, 0, w, h);

  const data = ctx.getImageData(0, 0, w, h);
  if (pass.contrast) boostContrast(data);
  return data;
}

export interface StillResult {
  hit: QrHit | null;
  /** Every pass tried, so a failure can say what was attempted. */
  attempted: string[];
}

/** Decode a QR from a File, Blob, or already-loaded image element. */
export async function decodeFromImage(input: File | Blob | HTMLImageElement): Promise<StillResult> {
  const attempted: string[] = [];

  let source: CanvasImageSource;
  let naturalW: number;
  let naturalH: number;
  let cleanup: (() => void) | null = null;

  if (input instanceof HTMLImageElement) {
    source = input;
    naturalW = input.naturalWidth;
    naturalH = input.naturalHeight;
  } else if (typeof createImageBitmap === "function") {
    // createImageBitmap applies EXIF orientation, which an <img> in a canvas
    // does not always do.
    const bitmap = await createImageBitmap(input);
    source = bitmap;
    naturalW = bitmap.width;
    naturalH = bitmap.height;
    cleanup = () => bitmap.close?.();
  } else {
    const url = URL.createObjectURL(input);
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("That file could not be read as an image."));
      img.src = url;
    });
    source = img;
    naturalW = img.naturalWidth;
    naturalH = img.naturalHeight;
    cleanup = () => URL.revokeObjectURL(url);
  }

  try {
    // The native detector first: it is the platform's own decoder and handles
    // perspective distortion better than anything in JS.
    const native = detector();
    if (native) {
      attempted.push("native detector");
      try {
        const found = await native.detect(source as any);
        if (found?.length) {
          return {
            hit: {
              text: found[0].rawValue,
              via: "photo (native detector)",
              corners: found[0].cornerPoints?.map((p: any) => ({ x: p.x, y: p.y })),
            },
            attempted,
          };
        }
      } catch {
        nativeDetectorInstance = null;
      }
    }

    const jsQR = await getJsQr();
    if (!jsQR) return { hit: null, attempted };

    for (const pass of PASSES) {
      attempted.push(pass.name);
      const data = draw(source, naturalW, naturalH, pass);
      if (!data) continue;
      const hit = jsQR(data.data, data.width, data.height, {
        inversionAttempts: "attemptBoth",
      });
      if (hit?.data) {
        return { hit: { text: hit.data, via: `photo (${pass.name})` }, attempted };
      }
    }
    return { hit: null, attempted };
  } finally {
    cleanup?.();
  }
}

/* ── Talking to the user about failures ────────────────────────────────────── */

/** Why getUserMedia is not going to work, or null if it should. */
export function cameraUnavailableReason(): string | null {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return "This browser does not support camera access. Use “Photo” or type the ID instead.";
  }
  // getUserMedia is gated on a secure context. The dev server binds 0.0.0.0,
  // so opening the app at http://192.168.x.x:3001 from a phone silently gets
  // no camera — worth naming, because the failure otherwise looks like a bug.
  if (typeof window !== "undefined" && !window.isSecureContext) {
    return (
      "Camera access needs a secure connection. This page is on plain http, " +
      "so open it over https or on localhost — or use “Photo” instead."
    );
  }
  return null;
}

export function cameraErrorMessage(err: unknown): string {
  const name = (err as any)?.name ?? "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera permission was declined. Allow it in your browser's site settings, or use “Photo” instead.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No camera was found on this device. Use “Photo” or type the ID instead.";
    case "NotReadableError":
    case "TrackStartError":
      return "The camera is in use by another app. Close it and try again.";
    case "AbortError":
      return "The camera stopped unexpectedly. Try again.";
    default:
      return (err as any)?.message || "The camera could not be started.";
  }
}

export function photoFailureMessage(attempted: string[]): string {
  return (
    "No QR code was found in that image. " +
    `Tried ${attempted.length} ways of reading it. ` +
    "It usually means the code is blurred, partly cut off, or too small in the " +
    "frame — fill more of the picture with the code and keep it flat. You can " +
    "also type the UPI ID underneath."
  );
}
