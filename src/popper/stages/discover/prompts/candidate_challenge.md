Challenge the retained scientific candidates from this fresh context, independently of their generator's conversation.
Candidate set: {subject}
Snapshot reference: {snapshot}
Sourced state: {state}
Read omitted cited contents with read_artifact; only reachable committed records are available.
Assess every candidate exactly once with submit_challenge. Cite the assessed candidate record and any other exact input sources.
Assess only the candidates in the specified candidate set, not every unrelated item in history.
Sources are complete ArtifactRef objects copied exactly from the supplied state or reachable
records, not candidate IDs, file paths or invented references. Retrieve omitted contents before
making a claim that depends on them; never infer their contents from a reference alone.
Check relevance, operational meaning, assumptions, plausible rival explanations and whether a predicted observation could distinguish them.
Return assessment, concerns, surviving rivals and possible discriminating_checks for each hypothesis_id. Do not force agreement or reject an exploratory attempt for uncertainty alone.
The tool accepts an assessments array. Each item has hypothesis_id, assessment, concerns,
rivals, discriminating_checks and sources. Provide at least one justified discriminating check
per candidate; it is a recommendation, not an executed observation. Empty concerns or rivals
are allowed when explained by the available context, but do not invent certainty.
Your assessment is attributed reasoning, not a measurement, validation verdict or permission to change researcher intent. Do not invent sources or empirical values. No execution tools are available here.
Fresh conversation context separates this assessment from generation; it does not establish
statistical independence or remove shared model bias. Literature retrieval is unavailable;
unresolved references and absent prior work remain limitations.
