import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

export function TrackBadges({
  cluster,
  genre,
  genres,
  language,
  hasError = false,
  inline = false,
}: {
  cluster?: string | null;
  genre?: string | null;
  genres?: string[] | null;
  language?: string | null;
  hasError?: boolean;
  inline?: boolean;
}) {
  const { data: genreOptions } = useQuery({
    queryKey: ["genres"],
    queryFn: api.genres,
    staleTime: 5 * 60 * 1000,
  });
  const genreLabel = (name: string): string =>
    genreOptions?.find((g) => g.name === name)?.name_ru ?? name;
  const firstGenre = genre ?? genres?.[0];

  const badges = (
    <>
      {hasError && (
        <Badge
          variant="destructive"
          className="max-w-full font-normal"
          title="processing error — see the track card"
        >
          <span className="truncate">error</span>
        </Badge>
      )}
      {cluster ? (
        <Badge
          variant="outline"
          className="max-w-full"
          title={`Mood cluster: tracks with a similar sound, grouped by audio features ("${cluster}")`}
        >
          <span className="truncate">{cluster}</span>
        </Badge>
      ) : (
        !inline && <span className="text-muted-foreground">—</span>
      )}
      {firstGenre && (
        <Badge
          variant="secondary"
          className="max-w-full font-normal"
          title={`Genre from Essentia audio analysis: ${firstGenre}`}
        >
          <span className="truncate">
            {genreLabel(firstGenre)}
            {language ? ` · ${language}` : ""}
          </span>
        </Badge>
      )}
      {!firstGenre && language && (
        <Badge
          variant="secondary"
          className="max-w-full font-normal"
          title={`Language of the lyrics: ${language}`}
        >
          <span className="truncate">{language}</span>
        </Badge>
      )}
    </>
  );

  if (inline) return badges;
  return (
    <span className="flex min-w-0 flex-col items-start gap-0.5 overflow-hidden">
      {badges}
    </span>
  );
}
