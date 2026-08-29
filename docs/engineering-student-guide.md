# Engineering student study guide

## Learning objective

By studying this project, you should be able to explain how a time-domain audio signal becomes a frequency-domain diagnostic feature, how a threshold converts a model output into an operational action, and why a production maintenance agent needs safeguards around that action.

## Suggested study path

### 1. Start with the app

Run the app and complete two trials:

- Healthy trial: anomaly toggle off, then simulate.
- Fault trial: anomaly toggle on, then simulate.

Record the sample rate, health state, anomaly score, and RUL displayed in each trial. The comparison shows the causal role of the injected high-frequency bursts.

### 2. Understand sampling

The app samples at 48 kHz. According to the Nyquist-Shannon idea, the highest unaliased frequency is half the sample rate, or 24 kHz. A 22 kHz signal can therefore be represented. If the sample rate were 32 kHz, content above 16 kHz would alias into a misleading lower frequency.

Questions to answer:

1. What sample rate would be needed to study a 30 kHz component?
2. What could go wrong if a WAV file is recorded at 16 kHz?
3. Why might an industrial sensor use a higher sample rate than a speech application?

### 3. Understand the synthetic signal

`generate_acoustic_data` combines:

- a base sine wave as a simplified rotating-machine tone;
- a third harmonic as a basic mechanical signature;
- Gaussian white noise as measurement/environment noise;
- damped 22 kHz bursts as a repeatable anomaly proxy.

The anomaly is educationally useful, but it is not a physical bearing model. Real defects can create modulation sidebands, impulsive transients, changing harmonics, and load-dependent signatures.

### 4. Understand FFT and spectral energy

The Fast Fourier Transform maps samples from time into frequency. The detector then asks a narrow question: how much spectral magnitude exists above 20 kHz?

This is a deliberately small feature pipeline:

```text
audio samples -> rFFT -> frequency bins -> bins above 20 kHz -> mean magnitude -> score
```

Explore these concepts next:

- windowing and spectral leakage;
- FFT bin width, approximately `sample_rate / number_of_samples`;
- RMS and crest factor for impulsive events;
- band-pass filters and envelope analysis;
- Mel scaling versus a linear frequency axis.

### 5. Read the Mel-spectrogram

A spectrogram shows how frequency energy changes over time. A Mel-spectrogram groups frequencies into perceptual bands and displays power in decibels. In this app, the heatmap is a visual explanation layer; the dummy detector itself uses FFT magnitude directly.

Look for short bright vertical traces in the high-frequency region during the injected-fault trial. Then explain why a spectrogram is more informative than a single average spectrum when the defect is intermittent.

### 6. Understand the agentic gate

The application calls the result an agentic response because it connects detection to a proposed action. In a real system, the decision should include model confidence, asset criticality, operating context, maintenance availability, and a human approval policy.

The current policy is simple:

```text
if anomaly_score > 75%:
    prepare maintenance request
else:
    continue monitoring
```

The displayed SAP payload is mock data. It is not an API call and should never be treated as proof that a work order exists in SAP.

## Practical exercises

### Exercise A: Change the base machine signature

Change one machine profile's `base_frequency` and observe the spectrogram. Explain which visual changes are expected and which should not affect the anomaly score.

### Exercise B: Replace the demo boost

Modify `calculate_anomaly` so the score depends more strongly on measured high-band energy and less on the `injected` flag. Add a small test script or notebook that compares healthy and injected signals.

### Exercise C: Add a confidence value

Return both `score` and `confidence`. Use confidence to prevent autonomous action when the audio is too short, clipped, silent, or outside the expected sample-rate range.

### Exercise D: Add human approval

Insert a Streamlit approval control between the threshold and the SAP payload. Explain why a critical industrial maintenance action should normally be reviewable and auditable.

### Exercise E: Design a real data contract

Write a JSON schema for a future maintenance request containing:

- asset identifier;
- sensor capture timestamp and sample rate;
- model version;
- anomaly score and confidence;
- suspected failure mode;
- recommended action;
- approval state and audit metadata.

## Responsible engineering checklist

- Validate against labeled data from both healthy and failed assets.
- Split train and test data by asset and time, not only by random audio window.
- Measure false positives because unnecessary maintenance is costly.
- Measure false negatives because missed bearing failures can be dangerous.
- Monitor sensor drift, microphone placement, machine load, and ambient noise.
- Preserve model version, input metadata, and decision logs.
- Keep a human-in-the-loop for safety-critical work orders.
- Never claim that a mock payload was written to SAP without verifying the real API response.

## Suggested extensions

1. Replace the rule-based detector with an anomaly model trained on log-Mel features.
2. Add a time-series history chart and configurable thresholds.
3. Add unit tests for signal generation, score ranges, and empty/corrupt audio handling.
4. Add a real SAP adapter behind an environment-configured API client.
5. Add authentication, secrets management, rate limits, and structured audit logging before any production deployment.
