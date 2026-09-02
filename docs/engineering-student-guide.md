# Engineering student study guide

## Learning objective

By studying this project, you should be able to explain how a time-domain audio signal becomes
a set of normalised diagnostic features, how those features are compared against a healthy
baseline to produce a score, how input validity limits what the score may be used for, and why
a production maintenance agent needs safeguards around the resulting action.

## Suggested study path

### 1. Start with the app

Run the app and complete three trials in the Simulate source:

- Healthy trial: both fault toggles off, **Generate signal**.
- Ultrasonic fault trial: *Inject 22 kHz micro-crack bursts* on.
- Bearing fault trial: *Inject bearing outer-race impacts* on (bursts off).

For each trial record the state, score, confidence, the driver named in the explanation and
which bars move in the evidence chart. The bearing trial is the important one: nothing changes
above 20 kHz, yet the verdict is CRITICAL.

### 2. Understand sampling

The app samples at 48 kHz. The highest unaliased frequency is half the sample rate, 24 kHz, so a
22 kHz signature can be represented. Load `robotic_arm_fault_16k.wav` from the sample library:
the Nyquist limit is 8 kHz, the diagnostic band is empty, the ultrasonic channels are reported
as unavailable, confidence drops to 0.4 and the state becomes *CRITICAL (unconfirmed)*.

Questions to answer:

1. What sample rate would be needed to study a 30 kHz component?
2. Why does the 16 kHz file still produce a high kurtosis, and why must the app refuse to act on it?
3. Why might an industrial sensor use a higher sample rate than a speech application?

### 3. Understand the synthetic signal

`acoustic_agent.synth` combines:

- a base sine wave as a simplified rotating-machine tone plus its third harmonic;
- Gaussian white noise as measurement / environment noise;
- optionally, damped 22 kHz bursts as a micro-crack proxy;
- optionally, impacts at the outer-race ball-pass frequency (BPFO = shaft × 3.585 ≈ 107 Hz)
  that ring a 5.2 kHz structural resonance, with slip jitter – the textbook bearing signature.

Every synthetic render is deterministic for a given seed and configuration; the sample WAV set
is produced by the same code.

### 4. Understand the features

Open `acoustic_agent/features.py`. Each channel is a pure function and each is normalised so
that microphone gain and recording length do not matter (test: `test_features_invariant_to_gain`).

```text
audio -> Welch PSD -> band power (dB re total)            band_power_db
                   -> band / reference band (dB)          band_contrast_db
      -> STFT      -> per-frame contrast, p98 - median    band_contrast_transient_db
      -> high-pass 2 kHz -> residual -> kurtosis          residual_kurtosis
                                      -> peak / RMS       residual_crest_factor
                                      -> |Hilbert| -> FFT -> strongest line vs floor
                                                          envelope_peak_snr_db
```

Concepts to explore: Welch averaging and its variance trade-off; why a ratio of two bands
cancels broadband noise; why a per-frame statistic recovers transients that averaging hides;
kurtosis of a Gaussian (3) versus an impulsive signal; the Hilbert envelope and why bearing
defect frequencies appear in it rather than in the raw spectrum.

### 5. Understand the baseline and the score

Open `acoustic_agent/detect.py`. Eight healthy renders give a mean and standard deviation per
channel. The standard deviation is floored (`config.std_floors`) because a synthetic baseline
is almost perfectly repeatable and a raw z-score would be meaningless. Then:

```text
z_c   = max(0, (x_c - mean_c) / max(std_c, floor_c))
z     = max_c w_c * z_c
score = 100 / (1 + exp(-(z - 3)))
```

Load `robotic_arm_healthy_noisy_48k.wav`: `band_power_db` is ~20σ above baseline (there is
simply more noise everywhere) but its weight is 0, so the verdict stays HEALTHY. Turn its weight
up in the Experiment tab and watch the false alarm appear. This is the whole argument for
normalised features.

### 6. Read the linear spectrogram

The spectrogram is a linear-frequency STFT in dB with the 20-24 kHz diagnostic band shaded. A
Mel axis was deliberately not used: it compresses the top octave into a few bins and hides the
very region this detector cares about. Look for short bright vertical traces inside the shaded
band during the burst trial, and for nothing in that band during the bearing trial.

### 7. Understand the agentic gate

The policy is now two-dimensional:

```text
if not valid:                      INVALID  – check the sensor, no verdict
elif score > 75 and conf >= 0.6:   CRITICAL – propose work order, wait for approval
elif score > 75:                   CRITICAL (unconfirmed) – re-capture first
elif score > 40:                   WARNING  – monitor more often
else:                              HEALTHY
```

The displayed SAP payload is mock data with a UUID ticket, timestamps, the configuration hash
and feature version so that it can be traced back to exactly the settings that produced it. It
is not an API call.

## Practical exercises

### Exercise A: Sweep the noise floor

In the Experiment tab, sweep `noise_std` from 0.01 to 0.3 with bursts as the fault mode. Plot
where the fault band and the healthy band overlap and explain which channel gives out first.

### Exercise B: Break the detector

Find a synthetic configuration where a healthy signal scores WARNING or above without touching
the demo boost. (Hints: very short duration, very low sample rate, extreme burst amplitude in
the reference band.) Explain what assumption you violated and whether a validity check should
catch it.

### Exercise C: Calibrate a real baseline

Record or download a few healthy machine clips (see the dataset survey in
`data/samples/README.md`), upload them as a custom baseline in the Experiment tab and re-score a
faulty clip. Compare the standard deviations with the synthetic floors.

### Exercise D: Add a channel

Add a spectral-kurtosis or a cyclostationarity channel to `features.py`, a default weight and
floor in `config.py`, a label in `decision.py`, bump `FEATURE_VERSION`, and write a test that
shows what it catches that the existing channels miss.

### Exercise E: Design a real data contract

Write a JSON schema for a future maintenance request containing asset identifier, capture
timestamp and sample rate, software and feature version, configuration hash, anomaly score and
confidence, suspected failure mode, recommended action, and approval / audit metadata. Compare
it with `decision.work_order_payload`.

## Responsible engineering checklist

- Validate against labelled data from both healthy and failed assets.
- Split train and test data by asset and time, not only by random audio window.
- Measure false positives because unnecessary maintenance is costly; the Batch tab reports them.
- Measure false negatives because missed bearing failures can be dangerous.
- Monitor sensor drift, microphone placement, machine load and ambient noise; re-calibrate the baseline.
- Preserve software version, feature version, configuration hash, input metadata and decision logs.
- Keep a human in the loop for safety-critical work orders.
- Never claim that a mock payload was written to SAP without verifying the real API response.

## Suggested extensions

1. Real-data loaders (MAFAULDA CSV, CWRU `.mat`) so the Batch tab can score public datasets.
2. Learned detector (isolation forest or autoencoder on the same feature vector) compared against the rule on ROC.
3. Time-series history of scores per asset with trend-based warnings.
4. A real SAP adapter behind an environment-configured API client with retries and idempotency keys.
5. Authentication, secrets management, rate limits and structured audit logging before any production deployment.
