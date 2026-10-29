# SOC Analyst Basics - Quick Notes

## 1. What a SOC analyst does

A SOC (Security Operations Center) monitors security telemetry, reviews detections, investigates suspicious activity, and coordinates response. L1 analysts commonly validate and triage alerts, gather evidence, document findings, and escalate. L2 analysts commonly correlate activity across sources, determine scope and impact, guide containment, and improve detections.

**Event → alert → incident:** an event is a recorded observation; an alert is a detection worth reviewing; an incident is a confirmed or credible security issue that needs coordinated response. An alert is not automatically an incident.

## 2. The first-pass triage checklist

1. Read the detection: what rule fired, when, and why?
2. Identify the affected user, device, application, and business importance.
3. Check the time range and timezone; use UTC when correlating sources.
4. Validate the evidence with relevant identity, endpoint, email, network, or cloud logs.
5. Separate confirmed facts from assumptions; note missing telemetry and confidence.
6. Assess scope and impact. Preserve evidence and follow the runbook.
7. Contain or escalate only under the organization’s approval and response policy.
8. Record a clear timeline, actions, open questions, and next owner.

## 3. Core security ideas

- **CIA triad:** confidentiality (who can see data), integrity (whether it is trustworthy and unchanged), availability (whether it can be used when needed).
- **Least privilege:** give each identity only the access it needs.
- **Vulnerability:** a weakness that could affect security. A CVE is a public identifier for a known vulnerability; CVSS is a severity score, not the whole business risk assessment.
- **False positive:** a benign event matched a detection. **False negative:** harmful activity was missed.
- **IOC:** an observable clue such as a file hash, domain, or IP address. **IOA:** behavior suggesting an attack. Neither is proof without context.
- **Hashing** creates a one-way digest useful for comparison. **Encryption** protects data with a key and can be reversed by an authorized key holder.

## 4. Networking quick reference

- **DNS:** resolves names and other records. Common port: 53 (UDP and TCP).
- **HTTP / HTTPS:** web traffic; HTTPS protects HTTP with TLS. Common ports: 80 / 443.
- **SSH:** secure remote administration. Common port: 22.
- **RDP:** remote desktop. Common port: 3389.
- **SMB:** Windows file and printer sharing. Common port: 445.
- **TCP** is connection-oriented; **UDP** is connectionless. Port numbers are conventions, so verify service context rather than relying on a port alone.
- **Ingress** enters an environment; **egress** leaves it. A firewall applies traffic rules; a proxy makes requests on a client’s behalf; NAT maps network addresses.

## 5. Identity and email clues

- **Brute force:** many password attempts against an account. **Password spraying:** a small set of passwords across many accounts. **Credential stuffing:** trying previously exposed username/password pairs on another service.
- Review sign-in result, MFA method, device, session, source, and actions after login. New geography or an unfamiliar IP is a clue, not proof.
- **Phishing:** deceptive messages that try to prompt unsafe action. Preserve the message and headers; do not open suspicious links on a production device.
- **SPF** lists authorized senders; **DKIM** checks a domain signature; **DMARC** applies sender-domain alignment policy. Passing these checks does not prove a message is safe.
- Unexpected mailbox forwarding rules and OAuth grants deserve review because they can expose data without obvious user activity.

## 6. Endpoint and network investigation

- For an endpoint alert, capture the process tree: parent, child, user, command line, file/hash, time, and network activity. Correlate with endpoint and email events.
- A rare domain, periodic connection, long DNS name, or large transfer is an investigation lead—not a verdict. Compare with a baseline and confirm which process or identity caused it.
- **EDR** collects endpoint detections and response context. **IDS** detects suspicious traffic; **IPS** can block it. A SIEM centralizes and correlates logs to support detections and investigations.

## 7. Incident response and evidence

Use the organization’s process to **identify, validate, scope, contain, eradicate, recover, and learn**. Containment limits ongoing impact; eradication removes the cause or unauthorized access; recovery restores services safely and monitors for recurrence.

Preserve original records. Note source, UTC timestamps, collection method, relevant IDs, and who handled the evidence. Follow chain-of-custody rules when applicable. Avoid deleting files, changing accounts, blocking destinations, or isolating systems outside approved authority.

## 8. Interview answer pattern

Use **what I know → what I would verify → how I would scope it → safe next action → what I would document/escalate**. State uncertainty directly. Avoid calling activity malicious from one indicator alone.

## 9. SIEM query habits

Start with a bounded time window. Filter on the relevant event type, group by useful identifiers, and inspect the underlying records before deciding. Validate field names against the actual schema. KQL and SPL examples in this course use illustrative training tables, not live telemetry.

