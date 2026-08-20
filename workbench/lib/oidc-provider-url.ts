function parsedUrl(value: string, label: string): URL {
  try {
    return new URL(value);
  } catch {
    throw new Error(`${label} is not an absolute URL`);
  }
}

export function providerRequestUrl(
  endpoint: string,
  issuer: string,
  internalBaseUrl: string | null,
): string {
  if (!internalBaseUrl) return endpoint;

  const endpointUrl = parsedUrl(endpoint, "OIDC provider endpoint");
  const issuerUrl = parsedUrl(issuer, "OIDC issuer");
  if (endpointUrl.username || endpointUrl.password || endpointUrl.hash) {
    throw new Error("OIDC provider endpoint contains forbidden URL components");
  }
  if (endpointUrl.origin !== issuerUrl.origin) {
    throw new Error("OIDC provider endpoint origin does not match issuer");
  }

  const internalUrl = parsedUrl(internalBaseUrl, "OIDC internal base URL");
  if (internalUrl.username || internalUrl.password || internalUrl.search || internalUrl.hash) {
    throw new Error("OIDC internal base URL contains forbidden URL components");
  }

  const basePath = internalUrl.pathname.replace(/\/$/, "");
  internalUrl.pathname = `${basePath}${endpointUrl.pathname}` || "/";
  internalUrl.search = endpointUrl.search;
  return internalUrl.toString();
}
