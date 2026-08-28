# Security Validation

Status: framework planned for Milestone 10; only repository and PostgreSQL checks exist today.

Validation scenarios must target local, owned, or explicitly authorized systems and use benign reversible behavior. Planned scenarios cover controlled resource abuse, a listening socket, a process/network chain, a Wi-Fi baseline anomaly, and calculation of observed detection coverage. A missing detection reduces reported coverage; it must never be hidden or replaced with fabricated data.

The validation set will also cover mass modification only inside generated temporary directories, authentication via synthetic fixtures or a controlled lab service, localhost/owned-host reconnaissance, reversible labeled persistence, and synthetic or owned-AP Wi-Fi observations. Cleanup is mandatory and tests never modify real documents or target third-party systems.

Reports will track expected, observed, detected, and missed behaviors; detection latency; severity; number of correlated incidents; agent CPU/RAM; and benign comparison outcomes. Coverage is based on observed detections, not inflated alert counts.
