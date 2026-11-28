export const ARTIFACT_REFERENCE_REQUEST_EVENT =
  "deerflow:artifact-reference-request";

export interface ArtifactReferenceRequest {
  threadId: string;
  artifactHandle: string;
}

export function requestArtifactReference(detail: ArtifactReferenceRequest) {
  window.dispatchEvent(
    new CustomEvent<ArtifactReferenceRequest>(
      ARTIFACT_REFERENCE_REQUEST_EVENT,
      { detail },
    ),
  );
}
