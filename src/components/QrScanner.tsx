import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, CameraOff, Image as ImageIcon, Keyboard, Loader2, Lightbulb, RefreshCw, X } from "lucide-react";
import {
  cameraErrorMessage,
  cameraUnavailableReason,
  decodeFromImage,
  decodeFromVideo,
  photoFailureMessage,
} from "../lib/qrDecode";

/**
 * Getting a UPI QR into the check.
 *
 * The page previously asked for "the QR code's contents" as text — which means
 * the string `upi://pay?pa=...`. Nobody has that. What a person has is a code
 * printed on a counter or sent to them as an image, so this offers the three
 * ways they can actually supply one:
 *
 *   Scan   live camera, decoded frame by frame on the device
 *   Photo  a picture or screenshot of the code
 *   Type   the original textarea, for a UPI ID or a payload they do have
 *
 * Nothing decoded here is opened or followed. It is shown as plain text and
 * handed to the existing /api/payee/check, so the analysis has one
 * implementation regardless of how the payload arrived.
 */

export type QrMode = "scan" | "photo" | "type";

interface Props {
  /** Called with the decoded payload. The parent decides whether to run the check. */
  onPayload: (payload: string, source: string) => void;
  /** Rendered inside the "Type" tab — the caller's existing textarea. */
  typeTab: React.ReactNode;
  /** Start on this tab. Defaults to "scan" where a camera is usable, else "photo". */
  initialMode?: QrMode;
}

const SUPPORTED_IMAGE = /^image\//;
// A phone photo is a few MB; 25 is generous and still rules out someone
// dropping a video in by mistake.
const MAX_IMAGE_BYTES = 25 * 1024 * 1024;

export default function QrScanner({ onPayload, typeTab, initialMode }: Props) {
  const cameraBlocked = cameraUnavailableReason();
  const [mode, setMode] = useState<QrMode>(
    initialMode ?? (cameraBlocked ? "photo" : "scan")
  );

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | null>(null);
  const scanningRef = useRef(false);

  const [cameraOn, setCameraOn] = useState(false);
  const [starting, setStarting] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [torchOn, setTorchOn] = useState(false);
  const [torchAvailable, setTorchAvailable] = useState(false);

  const [decoding, setDecoding] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [lastHit, setLastHit] = useState<{ text: string; via: string } | null>(null);
  const [dragOver, setDragOver] = useState(false);

  /* ── Camera lifecycle ───────────────────────────────────────────────────── */

  // One function for every teardown path. A camera left running is the bug
  // people notice — the indicator light stays on after they navigate away.
  const stopCamera = useCallback(() => {
    scanningRef.current = false;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOn(false);
    setTorchOn(false);
    setTorchAvailable(false);
  }, []);

  useEffect(() => stopCamera, [stopCamera]);
  // Switching away from the scan tab must release the camera too.
  useEffect(() => {
    if (mode !== "scan") stopCamera();
  }, [mode, stopCamera]);
  // And so must backgrounding the tab, which on mobile otherwise keeps the
  // camera held open while the user is in another app.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") stopCamera();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, [stopCamera]);

  const handleHit = useCallback(
    (text: string, via: string) => {
      setLastHit({ text, via });
      onPayload(text, via);
    },
    [onPayload]
  );

  const startCamera = useCallback(async () => {
    const blocked = cameraUnavailableReason();
    if (blocked) {
      setCameraError(blocked);
      return;
    }
    setStarting(true);
    setCameraError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        // ideal, not exact: `exact` fails outright on a laptop with only a
        // front camera, where the front camera is perfectly usable.
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      streamRef.current = stream;

      const video = videoRef.current;
      if (!video) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      video.srcObject = stream;
      // muted + playsInline are what stop iOS opening the stream fullscreen.
      video.muted = true;
      await video.play().catch(() => {});

      const track = stream.getVideoTracks()[0];
      const caps = (track as any)?.getCapabilities?.();
      setTorchAvailable(Boolean(caps?.torch));

      setCameraOn(true);
      scanningRef.current = true;

      // Throttled to ~8 decodes a second. Every frame is wasted work: a hand
      // holding a phone does not move meaningfully in 125ms, and on a mid-range
      // Android the unthrottled loop makes the preview stutter.
      let last = 0;
      const tick = async (now: number) => {
        if (!scanningRef.current) return;
        if (now - last >= 125) {
          last = now;
          const canvas = canvasRef.current;
          if (video && canvas) {
            try {
              const hit = await decodeFromVideo(video, canvas);
              if (hit && scanningRef.current) {
                stopCamera();
                handleHit(hit.text, hit.via);
                return;
              }
            } catch {
              // A single bad frame is not worth surfacing; keep scanning.
            }
          }
        }
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch (err) {
      setCameraError(cameraErrorMessage(err));
      stopCamera();
    } finally {
      setStarting(false);
    }
  }, [handleHit, stopCamera]);

  const toggleTorch = useCallback(async () => {
    const track = streamRef.current?.getVideoTracks()[0];
    if (!track) return;
    try {
      await (track as any).applyConstraints({ advanced: [{ torch: !torchOn }] });
      setTorchOn((v) => !v);
    } catch {
      setTorchAvailable(false);
    }
  }, [torchOn]);

  /* ── Still images ───────────────────────────────────────────────────────── */

  const handleFile = useCallback(
    async (file: File | null | undefined) => {
      if (!file) return;
      setPhotoError(null);
      setLastHit(null);

      if (!SUPPORTED_IMAGE.test(file.type)) {
        setPhotoError(
          `That is a ${file.type || "unknown"} file. Pick a photo or screenshot of the QR code.`
        );
        return;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        setPhotoError("That image is over 25 MB. A normal phone photo is well under that.");
        return;
      }

      setPreview((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(file);
      });
      setDecoding(true);
      try {
        const { hit, attempted } = await decodeFromImage(file);
        if (hit) {
          handleHit(hit.text, hit.via);
        } else {
          setPhotoError(photoFailureMessage(attempted));
        }
      } catch (err: any) {
        setPhotoError(err?.message || "That image could not be read.");
      } finally {
        setDecoding(false);
      }
    },
    [handleHit]
  );

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview);
    };
  }, [preview]);

  /* ── Presentation ───────────────────────────────────────────────────────── */

  const tabs: { id: QrMode; label: string; Icon: typeof Camera }[] = [
    { id: "scan", label: "Scan", Icon: Camera },
    { id: "photo", label: "Photo", Icon: ImageIcon },
    { id: "type", label: "Type it", Icon: Keyboard },
  ];

  const tabStyle = (active: boolean) => ({
    background: active ? "color-mix(in oklab, var(--brand) 14%, transparent)" : "transparent",
    border: active
      ? "1px solid color-mix(in oklab, var(--brand) 40%, transparent)"
      : "1px solid var(--line)",
    color: active ? "var(--brand)" : "var(--ink-muted)",
  });

  return (
    <div className="space-y-3">
      <div className="flex gap-2" role="tablist" aria-label="How to supply the QR code">
        {tabs.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={mode === id}
            onClick={() => {
              setMode(id);
              setCameraError(null);
              setPhotoError(null);
            }}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold transition-all duration-150"
            style={tabStyle(mode === id)}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {/* What was read, whichever tab produced it. Plain text, never a link. */}
      {lastHit && (
        <div
          className="rounded-xl p-3 space-y-1.5"
          style={{
            background: "color-mix(in oklab, var(--brand) 7%, transparent)",
            border: "1px solid color-mix(in oklab, var(--brand) 25%, transparent)",
          }}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--brand)" }}>
              Read from {lastHit.via}
            </span>
            <button
              type="button"
              onClick={() => setLastHit(null)}
              aria-label="Dismiss"
              style={{ color: "var(--ink-subtle)" }}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {/* break-all so a long payload wraps instead of stretching the card. */}
          <p className="font-mono text-xs break-all" style={{ color: "var(--ink)" }}>
            {lastHit.text}
          </p>
        </div>
      )}

      {mode === "scan" && (
        <div className="space-y-3">
          <div
            className="relative rounded-xl overflow-hidden"
            style={{ background: "var(--inset)", border: "1px solid var(--line)", aspectRatio: "4 / 3" }}
          >
            <video
              ref={videoRef}
              playsInline
              muted
              className="absolute inset-0 w-full h-full object-cover"
              style={{ display: cameraOn ? "block" : "none" }}
            />
            <canvas ref={canvasRef} className="hidden" />

            {cameraOn && (
              // A framing guide. People hold the code too far away, and a
              // target rectangle fixes that better than any instruction.
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div
                  className="rounded-2xl"
                  style={{
                    width: "62%",
                    aspectRatio: "1 / 1",
                    border: "3px solid color-mix(in oklab, var(--brand) 70%, transparent)",
                    boxShadow: "0 0 0 9999px color-mix(in oklab, black 34%, transparent)",
                  }}
                />
              </div>
            )}

            {!cameraOn && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-5 text-center">
                {cameraBlocked || cameraError ? (
                  <>
                    <CameraOff className="h-9 w-9" style={{ color: "var(--warn)" }} />
                    <p className="text-sm max-w-xs" style={{ color: "var(--ink-muted)" }}>
                      {cameraError ?? cameraBlocked}
                    </p>
                  </>
                ) : (
                  <>
                    <Camera className="h-9 w-9" style={{ color: "var(--ink-subtle)" }} />
                    <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
                      Point your camera at the QR code.
                    </p>
                  </>
                )}
                {!cameraBlocked && (
                  <button
                    type="button"
                    onClick={startCamera}
                    disabled={starting}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold"
                    style={{ background: "var(--brand)", color: "white" }}
                  >
                    {starting ? (
                      <><Loader2 className="h-4 w-4 animate-spin" /> Starting…</>
                    ) : cameraError ? (
                      <><RefreshCw className="h-4 w-4" /> Try again</>
                    ) : (
                      <><Camera className="h-4 w-4" /> Start camera</>
                    )}
                  </button>
                )}
              </div>
            )}
          </div>

          {cameraOn && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={stopCamera}
                className="flex-1 px-3 py-2 rounded-xl text-sm font-semibold"
                style={{ background: "var(--inset)", border: "1px solid var(--line)", color: "var(--ink-muted)" }}
              >
                Stop camera
              </button>
              {torchAvailable && (
                <button
                  type="button"
                  onClick={toggleTorch}
                  aria-pressed={torchOn}
                  className="px-3 py-2 rounded-xl text-sm font-semibold inline-flex items-center gap-1.5"
                  style={{
                    background: torchOn
                      ? "color-mix(in oklab, var(--warn) 16%, transparent)"
                      : "var(--inset)",
                    border: "1px solid var(--line)",
                    color: torchOn ? "var(--warn)" : "var(--ink-muted)",
                  }}
                >
                  <Lightbulb className="h-4 w-4" />
                  {torchOn ? "Light on" : "Light"}
                </button>
              )}
            </div>
          )}

          <p className="text-xs" style={{ color: "var(--ink-subtle)" }}>
            The camera feed stays on this device — frames are read here and never uploaded.
          </p>
        </div>
      )}

      {mode === "photo" && (
        <div className="space-y-3">
          <label
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              handleFile(e.dataTransfer.files?.[0]);
            }}
            className="block rounded-xl p-6 text-center cursor-pointer transition-all duration-150"
            style={{
              background: dragOver
                ? "color-mix(in oklab, var(--brand) 8%, transparent)"
                : "var(--inset)",
              border: dragOver
                ? "2px dashed color-mix(in oklab, var(--brand) 50%, transparent)"
                : "2px dashed var(--line)",
            }}
          >
            <input
              type="file"
              accept="image/*"
              // On a phone this offers the camera directly as well as the
              // gallery, which is the fallback when live scanning is blocked.
              capture="environment"
              className="hidden"
              onChange={(e) => {
                handleFile(e.target.files?.[0]);
                // Reset so picking the same file twice still fires onChange.
                e.target.value = "";
              }}
            />
            {decoding ? (
              <div className="flex flex-col items-center gap-2">
                <Loader2 className="h-8 w-8 animate-spin" style={{ color: "var(--brand)" }} />
                <span className="text-sm" style={{ color: "var(--ink-muted)" }}>Reading the code…</span>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <ImageIcon className="h-8 w-8" style={{ color: "var(--ink-subtle)" }} />
                <span className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                  Take a photo or choose an image
                </span>
                <span className="text-xs" style={{ color: "var(--ink-subtle)" }}>
                  A screenshot of a payment request works too. Drag one in, or tap to browse.
                </span>
              </div>
            )}
          </label>

          {preview && (
            <div className="flex items-start gap-3">
              <img
                src={preview}
                alt="The image you supplied"
                className="rounded-lg"
                style={{ width: 84, height: 84, objectFit: "cover", border: "1px solid var(--line)" }}
              />
              <p className="text-xs flex-1" style={{ color: "var(--ink-subtle)" }}>
                Read on this device. The image is not uploaded anywhere.
              </p>
            </div>
          )}

          {photoError && (
            <div
              className="rounded-xl p-3 text-sm"
              style={{
                background: "color-mix(in oklab, var(--warn) 10%, transparent)",
                border: "1px solid color-mix(in oklab, var(--warn) 28%, transparent)",
                color: "var(--ink-muted)",
              }}
            >
              {photoError}
            </div>
          )}
        </div>
      )}

      {mode === "type" && typeTab}
    </div>
  );
}
