import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const steps = ["Front", "Back", "Type", "Docs", "Submit"];

const frontFieldLabels = {
  full_name: "Name",
  first_name: "First name",
  last_name: "Last name",
  address_line: "Street address",
  city: "City",
  province: "Province",
  postal_code: "Postal code",
  license_number: "License number",
  issue_date: "Issue date",
  expiry_date: "Expiry date",
  date_of_birth: "Date of birth",
  reference_number: "Reference number",
  height: "Height",
  sex: "Sex",
  license_class: "Class",
  conditions: "Conditions",
};

function App() {
  const isAdmin = window.location.pathname.startsWith("/admin");
  return isAdmin ? <AdminDashboard /> : <IntakeApp />;
}

function IntakeApp() {
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
    <main className="mobile-stage">
      <section className="phone-shell" aria-label="iPhone 15 Pro Max optimized app">
        <div className="phone-bezel">
          <div className="dynamic-island" />
          <div className="app-screen">
            <header className="mobile-header">
              <div>
                <p className="eyebrow">KYC intake</p>
                <h1>Verify identity</h1>
              </div>
              <a className="admin-link" href="/admin">
                Admin
              </a>
            </header>

            <Progress currentStep={effectiveStep} />

            <section className="mobile-card">
              {effectiveStep === 0 && (
                <CaptureStep
                  title="Front of license"
                  description="Fill the frame with the front of the license."
                  photo={frontPhoto}
                  onCapture={(blob) => storePhoto("front", blob)}
                  onRetake={() => clearPhoto("front")}
                  nextDisabled={!frontPhoto}
                  onNext={() => setStep(1)}
                />
              )}

              {effectiveStep === 1 && (
                <CaptureStep
                  title="Back of license"
                  description="Capture the back clearly, especially the center-right number."
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
          </div>
        </div>
      </section>
    </main>
  );
}

function Progress({ currentStep }) {
  return (
    <ol className="progress" aria-label="Progress">
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
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
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
            ? "Camera permission was denied. Allow camera access and refresh."
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
      0.96
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
        <div className="camera-frame">
          <video ref={videoRef} autoPlay playsInline muted />
          <div className="license-guide" />
          {isStarting && <div className="camera-loading">Starting camera...</div>}
        </div>
      )}
      <div className="button-row sticky-actions">
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
        title="Client type"
        description="Entity clients need articles of incorporation."
      />
      <div className="choice-grid">
        <button
          className={clientType === "individual" ? "choice selected" : "choice"}
          type="button"
          onClick={() => onChange("individual")}
        >
          <strong>Individual</strong>
          <span>No corporate document required.</span>
        </button>
        <button
          className={clientType === "entity" ? "choice selected" : "choice"}
          type="button"
          onClick={() => onChange("entity")}
        >
          <strong>Corporation or entity</strong>
          <span>Collect articles before submitting.</span>
        </button>
      </div>
      <div className="button-row sticky-actions">
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
        title="Articles"
        description="Upload the articles of incorporation."
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
        <input type="file" onChange={(event) => handleFiles(event.target.files)} />
        <span>{file ? file.name : "Tap to upload"}</span>
        <small>
          {file ? `${Math.ceil(file.size / 1024)} KB selected` : "PDF, image, or document"}
        </small>
      </label>
      <div className="button-row sticky-actions">
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
  const frontFields = result?.ocr?.front?.fields || {};
  const backFields = result?.ocr?.back?.fields || {};

  return (
    <div className="step-content">
      <StepHeader
        title={result ? "Ready for review" : "Submit packet"}
        description={
          result
            ? "The admin dashboard now has the photos and extracted fields."
            : "Send the photos to the local FastAPI OCR workflow."
        }
      />
      <div className="review-grid">
        <PhotoCard title="Front" photo={frontPhoto} />
        <PhotoCard title="Back" photo={backPhoto} />
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
      {result && (
        <section className="ocr-result">
          <FieldGrid fields={frontFields} labels={frontFieldLabels} />
          <div className="review-detail">
            <strong>Back license number</strong>
            <span>{backFields.license_number || "Needs manual review"}</span>
          </div>
          <a className="text-link" href="/admin">
            Open admin dashboard
          </a>
        </section>
      )}
      <div className="button-row sticky-actions">
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
            {isSubmitting ? "Extracting..." : "Submit intake"}
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
      {photo ? <img src={photo.previewUrl} alt={`${title} license`} /> : <div />}
      <figcaption>{title}</figcaption>
    </figure>
  );
}

function FieldGrid({ fields, labels }) {
  return (
    <div className="field-grid">
      {Object.entries(labels).map(([key, label]) => (
        <div className="field-row" key={key}>
          <span>{label}</span>
          <strong>{fields?.[key] || "Needs review"}</strong>
        </div>
      ))}
    </div>
  );
}

function AdminDashboard() {
  const [intakes, setIntakes] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [selected, setSelected] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadIntakes() {
    setIsLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/intakes`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load intakes.");
      setIntakes(data.intakes || []);
      if (!selectedId && data.intakes?.[0]) setSelectedId(data.intakes[0].intake_id);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadIntakes();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }

    async function loadSelected() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/intakes/${selectedId}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not load intake.");
        setSelected(data);
      } catch (loadError) {
        setError(loadError.message);
      }
    }

    loadSelected();
  }, [selectedId]);

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <p className="eyebrow">Admin review</p>
          <h1>KYC dashboard</h1>
        </div>
        <div className="admin-actions">
          <a className="secondary-button" href="/">
            Intake app
          </a>
          <button className="primary-button" type="button" onClick={loadIntakes}>
            Refresh
          </button>
        </div>
      </header>

      {error && <div className="form-error">{error}</div>}

      <section className="admin-grid">
        <aside className="intake-list">
          <h2>Submissions</h2>
          {isLoading && <p className="muted">Loading...</p>}
          {!isLoading && intakes.length === 0 && (
            <p className="muted">No intakes submitted yet.</p>
          )}
          {intakes.map((intake) => (
            <button
              className={selectedId === intake.intake_id ? "intake-card selected" : "intake-card"}
              key={intake.intake_id}
              type="button"
              onClick={() => setSelectedId(intake.intake_id)}
            >
              <strong>{intake.name || "Name needs review"}</strong>
              <span>{intake.license_number || "License needs review"}</span>
              <small>{new Date(intake.created_at).toLocaleString()}</small>
            </button>
          ))}
        </aside>

        <section className="admin-detail">
          {selected ? <AdminRecord record={selected} /> : <EmptyAdminState />}
        </section>
      </section>
    </main>
  );
}

function AdminRecord({ record }) {
  const frontFields = record.ocr.front.fields;
  const backFields = record.ocr.back.fields;
  const frontUrl = `${API_BASE_URL}/api/intakes/${record.intake_id}/files/license_front`;
  const backUrl = `${API_BASE_URL}/api/intakes/${record.intake_id}/files/license_back`;
  const articlesUrl = record.files.articles
    ? `${API_BASE_URL}/api/intakes/${record.intake_id}/files/articles`
    : null;

  return (
    <div className="admin-record">
      <div className="record-head">
        <div>
          <p className="eyebrow">{record.client_type}</p>
          <h2>{frontFields.full_name || "Name needs review"}</h2>
        </div>
        <span className="status-pill">Ready for review</span>
      </div>

      <div className="admin-photo-grid">
        <figure>
          <img src={frontUrl} alt="Front license" />
          <figcaption>Front license</figcaption>
        </figure>
        <figure>
          <img src={backUrl} alt="Back license" />
          <figcaption>Back license</figcaption>
        </figure>
      </div>

      <section className="admin-section">
        <h3>Extracted front details</h3>
        <FieldGrid fields={frontFields} labels={frontFieldLabels} />
      </section>

      <section className="admin-section">
        <h3>Back extraction</h3>
        <div className="review-detail">
          <strong>License number</strong>
          <span>{backFields.license_number || "Needs manual review"}</span>
        </div>
      </section>

      {articlesUrl && (
        <section className="admin-section">
          <h3>Entity document</h3>
          <a className="text-link" href={articlesUrl} target="_blank" rel="noreferrer">
            Open articles of incorporation
          </a>
        </section>
      )}

      <section className="admin-section">
        <h3>Raw OCR text</h3>
        <details>
          <summary>Front raw text</summary>
          <pre>{record.ocr.front.raw_text || "No text detected."}</pre>
        </details>
        <details>
          <summary>Back raw text</summary>
          <pre>{record.ocr.back.raw_text || "No text detected."}</pre>
        </details>
      </section>
    </div>
  );
}

function EmptyAdminState() {
  return (
    <div className="empty-state">
      <h2>No intake selected</h2>
      <p>Submitted KYC packets will appear here for photo and field review.</p>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
