export type CoverImageSize = 150 | 500;

export function coverImageUrl(
  source: string | null | undefined,
  size: CoverImageSize,
): string | null {
  const value = source?.trim();
  if (!value) return null;
  const params = new URLSearchParams({ url: value, size: String(size) });
  return `/api/v1/cover-image?${params.toString()}`;
}
