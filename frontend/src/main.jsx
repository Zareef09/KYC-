import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const steps = [
  "Front license",
  "Back license",
  "Client type",
  "Articles",
  "Review",
];

function App() {
  const [step, setStep] = useState(0);
  const [frontPhoto, setFrontPhoto] = useState(null);
  const [backPhoto, setBackPhoto] = useState(null);
  const [clientType, setClientType] = useState("individual");
  const [articlesFile, setArticlesFile] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [result, setResult] = useState(null);

  const needsArticles = clientType === "entity";
  const effectiveStep = !needsArticles && step === 3 ? 4 : step;
  const canSubmit = frontPhoto && backPhoto && (!needsArticles || articlesFile);

  function storePhoto(side, blob) {
    const photo = {
      blob,
      previewUrl: URL.createObjectURL(blob),
      filename: `license-${side}.jpg`,
    };

    if (side === "front") {
      if (frontPhoto?.previewUrl) URL.revokeObjectURL(frontPhoto.previewUrl);
      setFrontPhoto(photo);
      setStep(1);
    } else {
      if (backPhoto?.previewUrl) URL.revokeObjectURL(backPhoto.previewUrl);
      setBackPhoto(photo);
      setStep(2);
    }
  }

  function clearPhoto(side) {
    if (side === "front") {
      if (frontPhoto?.previewUrl) URL.revokeObjectURL(frontPhoto.previewUrl);
      setFrontPhoto(null);
    } else {
      if (backPhoto?.previewUrl) URL.revokeObjectURL(backPhoto.previewUrl);
      setBackPhoto(null);
    }
  }

  function reset() {
    [frontPhoto, backPhoto].forEach((photo) => {
      if (photo?.previewUrl) URL.revokeObjectURL(photo.previewUrl);
    });
    setStep(0);
    setFrontPhoto(null);
    setBackPhoto(null);
    setClientType("individual");
    setArticlesFile(null);
    setIsSubmitting(false);
    setSubmitError("");
    setResult(null);
  }

  async function submitIntake() {
    if (!canSubmit) return;

    const formData = new FormData();
    formData.append("client_type", clientType);
    formData.append("license_front", frontPhoto.blob, frontPhoto.filename);
    formData.append("license_back", backPhoto.blob, backPhoto.filename);

    if (needsArticles && articlesFile) {
      formData.append("articles", articlesFile, articlesFile.name);
    }

    setIsSubmitting(true);
    setSubmitError("");

    try {
      const response = await fetch(`${API_BASE_URL}/api/intakes`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data.detail || "The intake could not be submitted.");
      }

      setResult(data);
      setStep(4);
    } catch (error) {
      setSubmitError(error.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="topbar" aria-label="KYC intake progress">
        <div>
          <p className="eyebrow">Client onboarding</p>
          <h1>Simple KYC intake</h1>
        </div>
        <Progress currentStep={effectiveStep} />
      </section>

      <section className="workspace">
        <aside className="summary-panel" aria-label="Captured intake summary">
          <h2>Packet</h2>
          <SummaryItem label="Front license" complete={Boolean(frontPhoto)} />
          <SummaryItem label="Back license" complete={Boolean(backPhoto)} />
          <SummaryItem
            label="Client type"
            complete={Boolean(clientType)}
            detail={clientType === "entity" ? "Entity" : "Individual"}
          />
          {needsArticles && (
            <SummaryItem
              label="Articles"
              complete={Boolean(articlesFile)}
              detail={articlesFile?.name}
            />
          )}
        </aside>

        <section className="flow-panel">
          {effectiveStep === 0 && (
            <CaptureStep
              title="Capture the front of the license"
              description="Place the front of the driver's license inside the camera frame."
              photo={frontPhoto}
              onCapture={(blob) => storePhoto("front", blob)}
              onRetake={() => clearPhoto("front")}
              nextDisabled={!frontPhoto}
              onNext={() => setStep(1)}
            />
          )}

          {effectiveStep === 1 && (
            <CaptureStep
              title="Capture the back of the license"
              description="Flip the license over and capture the barcode side."
              photo={backPhoto}
              onCapture={(blob) => storePhoto("back", blob)}
              onRetake={() => clearPhoto("back")}
              nextDisabled={!backPhoto}
              onBack={() => setStep(0)}
              onNext={() => setStep(2)}
            />
          )}

          {effectiveStep === 2 && (
            <ClientTypeStep
              clientType={clientType}
              onChange={(value) => {
                setClientType(value);
                if (value === "individual") setArticlesFile(null);
              }}
              onBack={() => setStep(1)}
              onNext={() => setStep(clientType === "entity" ? 3 : 4)}
            />
          )}

          {effectiveStep === 3 && (
            <ArticlesStep
              file={articlesFile}
              onFile={setArticlesFile}
              onBack={() => setStep(2)}
              onNext={() => setStep(4)}
            />
          )}

          {effectiveStep === 4 && (
            <ReviewStep
              frontPhoto={frontPhoto}
              backPhoto={backPhoto}
              clientType={clientType}
              articlesFile={articlesFile}
              canSubmit={canSubmit}
              isSubmitting={isSubmitting}
              submitError={submitError}
              result={result}
              onBack={() => setStep(needsArticles ? 3 : 2)}
              onSubmit={submitIntake}
              onReset={reset}
            />
          )}
        </section>
      </section>
    </main>
  );
}

function Progress({ currentStep }) {
  return (
    <ol className="progress">
      {steps.map((label, index) => (
        <li
          key={label}
          className={index <= currentStep ? "active" : ""}
          aria-current={index === currentStep ? "step" : undefined}
        >
          <span>{index + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}

function SummaryItem({ label, complete, detail }) {
  return (
    <div className="summary-item">
      <span className={complete ? "status-dot complete" : "status-dot"} />
      <div>
        <strong>{label}</strong>
        <small>{detail || (complete ? "Ready" : "Pending")}</small>
      </div>
    </div>
  );
}

function CaptureStep({
  title,
  description,
  photo,
  onCapture,
  onRetake,
  onBack,
  onNext,
  nextDisabled,
}) {
  return (
    <div className="step-content">
      <StepHeader title={title} description={description} />
      {photo ? (
        <div className="captured-preview">
          <img src={photo.previewUrl} alt={`${title} preview`} />
          <div className="button-row">
            {onBack && (
              <button className="secondary-button" type="button" onClick={onBack}>
                Back
              </button>
            )}
            <button className="secondary-button" type="button" onClick={onRetake}>
              Retake
            </button>
            <button
              className="primary-button"
              type="button"
              onClick={onNext}
              disabled={nextDisabled}
            >
              Continue
            </button>
          </div>
        </div>
      ) : (
        <CameraCapture onCapture={onCapture} onBack={onBack} />
      )}
    </div>
  );
}

function CameraCapture({ onCapture, onBack }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [cameraError, setCameraError] = useState("");
  const [isStarting, setIsStarting] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function startCamera() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setCameraError("This browser does not support camera capture.");
        setIsStarting(false);
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });

        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch (error) {
        setCameraError(
          error.name === "NotAllowedError"
            ? "Camera permission was denied. Allow camera access and refresh to continue."
            : "The camera could not be started on this device."
        );
      } finally {
        if (!cancelled) setIsStarting(false);
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  function captureFrame() {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob(
      (blob) => {
        if (blob) onCapture(blob);
      },
      "image/jpeg",
      0.92
    );
  }

  return (
    <div className="camera-box">
      {cameraError ? (
        <div className="camera-error" role="alert">
          <strong>Camera unavailable</strong>
          <p>{cameraError}</p>
        </div>
      ) : (
        <>
          <video ref={videoRef} autoPlay playsInline muted />
          {isStarting && <div className="camera-loading">Starting camera...</div>}
        </>
      )}
      <div className="button-row">
        {onBack && (
          <button className="secondary-button" type="button" onClick={onBack}>
            Back
          </button>
        )}
        <button
          className="primary-button"
          type="button"
          onClick={captureFrame}
          disabled={Boolean(cameraError) || isStarting}
        >
          Capture photo
        </button>
      </div>
    </div>
  );
}

function ClientTypeStep({ clientType, onChange, onBack, onNext }) {
  return (
    <div className="step-content">
      <StepHeader
        title="Who is the prospective client?"
        description="Articles of incorporation are only collected for entity clients."
      />
      <div className="choice-grid">
        <button
          className={clientType === "individual" ? "choice selected" : "choice"}
          type="button"
          onClick={() => onChange("individual")}
        >
          <strong>Individual</strong>
          <span>Skip corporate document collection.</span>
        </button>
        <button
          className={clientType === "entity" ? "choice selected" : "choice"}
          type="button"
          onClick={() => onChange("entity")}
        >
          <strong>Corporation or entity</strong>
          <span>Collect articles of incorporation.</span>
        </button>
      </div>
      <div className="button-row">
        <button className="secondary-button" type="button" onClick={onBack}>
          Back
        </button>
        <button className="primary-button" type="button" onClick={onNext}>
          Continue
        </button>
      </div>
    </div>
  );
}

function ArticlesStep({ file, onFile, onBack, onNext }) {
  const [isDragging, setIsDragging] = useState(false);

  function handleFiles(fileList) {
    const [selectedFile] = Array.from(fileList || []);
    if (selectedFile) onFile(selectedFile);
  }

  return (
    <div className="step-content">
      <StepHeader
        title="Upload articles of incorporation"
        description="Drop the entity document here or select it from the device."
      />
      <label
        className={isDragging ? "drop-zone dragging" : "drop-zone"}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
      >
        <input
          type="file"
          onChange={(event) => handleFiles(event.target.files)}
        />
        <span>{file ? file.name : "Drop file or browse"}</span>
        <small>{file ? `${Math.ceil(file.size / 1024)} KB selected` : "PDF, image, or document file"}</small>
      </label>
      <div className="button-row">
        <button className="secondary-button" type="button" onClick={onBack}>
          Back
        </button>
        <button
          className="primary-button"
          type="button"
          onClick={onNext}
          disabled={!file}
        >
          Continue
        </button>
      </div>
    </div>
  );
}

function ReviewStep({
  frontPhoto,
  backPhoto,
  clientType,
  articlesFile,
  canSubmit,
  isSubmitting,
  submitError,
  result,
  onBack,
  onSubmit,
  onReset,
}) {
  return (
    <div className="step-content">
      <StepHeader
        title={result ? "Intake collected" : "Review and submit"}
        description={
          result
            ? "The backend saved the files temporarily and returned OCR text."
            : "Confirm the packet before sending it to the local FastAPI backend."
        }
      />
      <div className="review-grid">
        <PhotoCard title="Front license" photo={frontPhoto} />
        <PhotoCard title="Back license" photo={backPhoto} />
      </div>
      <div className="review-detail">
        <strong>Client type</strong>
        <span>{clientType === "entity" ? "Corporation or entity" : "Individual"}</span>
      </div>
      {clientType === "entity" && (
        <div className="review-detail">
          <strong>Articles</strong>
          <span>{articlesFile?.name || "Missing"}</span>
        </div>
      )}
      {submitError && (
        <div className="form-error" role="alert">
          {submitError}
        </div>
      )}
      {result && <OcrResult result={result} />}
      <div className="button-row">
        {!result && (
          <button className="secondary-button" type="button" onClick={onBack}>
            Back
          </button>
        )}
        {result ? (
          <button className="primary-button" type="button" onClick={onReset}>
            Start new intake
          </button>
        ) : (
          <button
            className="primary-button"
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit || isSubmitting}
          >
            {isSubmitting ? "Submitting..." : "Submit intake"}
          </button>
        )}
      </div>
    </div>
  );
}

function StepHeader({ title, description }) {
  return (
    <header className="step-header">
      <h2>{title}</h2>
      <p>{description}</p>
    </header>
  );
}

function PhotoCard({ title, photo }) {
  return (
    <figure className="photo-card">
      {photo ? <img src={photo.previewUrl} alt={title} /> : <div />}
      <figcaption>{title}</figcaption>
    </figure>
  );
}

function OcrResult({ result }) {
  return (
    <section className="ocr-result" aria-label="Extracted license text">
      <div className="review-detail">
        <strong>Intake ID</strong>
        <span>{result.intake_id}</span>
      </div>
      <OcrBlock title="Front OCR" data={result.ocr.front} />
      <OcrBlock title="Back OCR" data={result.ocr.back} />
    </section>
  );
}

function OcrBlock({ title, data }) {
  const hintEntries = useMemo(
    () =>
      Object.entries(data.hints || {}).filter(([, values]) => values.length > 0),
    [data]
  );

  return (
    <article className="ocr-block">
      <h3>{title}</h3>
      {hintEntries.length > 0 && (
        <div className="hint-list">
          {hintEntries.map(([label, values]) => (
            <div key={label}>
              <strong>{label.replaceAll("_", " ")}</strong>
              <span>{values.join(" | ")}</span>
            </div>
          ))}
        </div>
      )}
      <pre>{data.raw_text || "No text detected."}</pre>
    </article>
  );
}

createRoot(document.getElementById("root")).render(<App />);
