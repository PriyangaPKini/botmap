import io
import json
import re
import sys
from typing import List, Optional, Tuple
from urllib.request import urlopen

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as fs
import pyarrow.parquet as pq

from .filters import ParsedFilter, apply_post_filters, combine, post_filter_fields
from .models import BBox

STAC_CATALOG_URL = "https://stac.overturemaps.org/catalog.json"

# Release IDs look like "2026-08-19.0".
_RELEASE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.\d+")

# Cache for STAC catalog to avoid repeated network calls
_cached_stac_catalog = None

# Allows for optional import of additional dependencies
try:
    from geopandas import GeoDataFrame

    HAS_GEOPANDAS = True
except ImportError:
    HAS_GEOPANDAS = False

    class GeoDataFrame:
        pass


def _get_stac_catalog() -> dict:
    """
    Fetch and cache the STAC catalog.

    Returns
    -------
    dict: The STAC catalog JSON
    """
    global _cached_stac_catalog

    if _cached_stac_catalog is not None:
        return _cached_stac_catalog

    try:
        with urlopen(STAC_CATALOG_URL) as response:
            catalog = json.load(response)

        # Cache the catalog
        _cached_stac_catalog = catalog
        return catalog

    except Exception as e:
        raise Exception(f"Could not fetch STAC catalog: {e}") from e


def _release_from_href(href: str) -> Optional[str]:
    """Pull a release ID like "2026-08-19.0" out of a STAC child link.

    The catalog has served both relative ("./2026-08-19.0/catalog.json") and
    absolute ("https://stac.overturemaps.org/2026-08-19.0/catalog.json") hrefs,
    so match the ID itself rather than a position in the path.
    """
    match = _RELEASE_RE.search(href)
    return match.group(0) if match else None


def get_available_releases() -> Tuple[List[str], str]:
    """
    Fetch available releases from the STAC catalog.

    Returns
    -------
    Tuple of (all_releases, latest_release) where:
        - all_releases is a list of release version strings
        - latest_release is the latest release version string
    """
    catalog = _get_stac_catalog()

    latest_release = catalog.get("latest")

    # Extract release versions from the child links
    releases = []
    for link in catalog.get("links", []):
        if link.get("rel") == "child":
            release_version = _release_from_href(link.get("href", ""))
            if release_version:
                releases.append(release_version)

    return releases, latest_release


def get_latest_release() -> str:
    """
    Get the latest release version.

    Returns
    -------
    str: The latest release version
    """
    _, latest = get_available_releases()
    return latest


# For backwards compatibility, expose ALL_RELEASES as a list
# This will be populated dynamically when first accessed
def _get_all_releases():
    releases, _ = get_available_releases()
    return releases


# Lazy evaluation property-like access
class _ReleasesProxy:
    def __getitem__(self, index):
        return _get_all_releases()[index]

    def __iter__(self):
        return iter(_get_all_releases())

    def __len__(self):
        return len(_get_all_releases())

    def __repr__(self):
        return repr(_get_all_releases())


ALL_RELEASES = _ReleasesProxy()


def _coerce_bbox(
    bbox: BBox | tuple[float, float, float, float] | list[float] | None,
) -> BBox | None:
    """Normalize bbox input to a BBox instance."""
    if bbox is None:
        return None

    if isinstance(bbox, BBox):
        return bbox

    if len(bbox) != 4:
        raise ValueError("bbox must contain exactly 4 numeric values")

    return BBox(
        xmin=float(bbox[0]),
        ymin=float(bbox[1]),
        xmax=float(bbox[2]),
        ymax=float(bbox[3]),
    )


def _get_files_from_stac(
    theme: str, overture_type: str, bbox: BBox, release: str
) -> Optional[List[str]]:
    """
    Returns a list of bucket/key paths using the STAC-geoparquet index
    """
    stac_url = f"https://stac.overturemaps.org/{release}/collections.parquet"
    try:
        # Arrow can't read HTTP URLs directly; read into memory first
        with urlopen(stac_url) as response:
            data = response.read()
            buffer = io.BytesIO(data)
            stac_table = pq.read_table(buffer)

        feature_type_filter = (pc.field("collection") == overture_type) & (
            pc.field("type") == "Feature"
        )

        xmin, ymin, xmax, ymax = bbox.as_tuple()
        bbox_filter = (
            (pc.field("bbox", "xmin") < xmax)
            & (pc.field("bbox", "xmax") > xmin)
            & (pc.field("bbox", "ymin") < ymax)
            & (pc.field("bbox", "ymax") > ymin)
        )

        combined_filter = feature_type_filter & bbox_filter
        table = stac_table.filter(combined_filter)

        if table.num_rows > 0:
            file_paths = table.column("assets").to_pylist()

            # clip out the "s3://" prefix
            s3_paths = [
                path["aws"]["alternate"]["s3"]["href"][len("s3://") :]
                for path in file_paths
            ]
            return s3_paths
        else:
            print(
                f"No data found for release {release} in query bbox {bbox.as_tuple()}.",
                file=sys.stderr,
            )
            return []

    except Exception as e:
        print(f"Error reading STAC index at {stac_url}: {e}", file=sys.stderr)
        return None


def _record_batch_reader_from_dataset(
    dataset: ds.Dataset,
    filter_expr=None,
    columns=None,
    post_filters=(),
) -> Optional[pa.RecordBatchReader]:
    """
    Create a RecordBatchReader from an S3 dataset with optional filtering.

    Parameters
    ----------
    dataset: pyarrow dataset
        Dataset to read from
    filter_expr: pyarrow expression, optional
        Filter to apply when reading the dataset
    columns: list of str, optional
        Project to these columns only. An enumeration command reads one
        field out of ~28, so projecting avoids fetching the rest.
    post_filters: list of ParsedFilter, optional
        Filters the scan cannot push down, applied to each batch after it
        is read. Fields they need are read and then dropped again.

    Returns
    -------
    RecordBatchReader with the feature data, or None if error occurs
    """
    try:
        batches = _scan_batches(dataset, filter_expr, columns, post_filters)

        # Filter out empty batches to avoid downstream issues
        non_empty_batches = (b for b in batches if b.num_rows > 0)

        schema = dataset.schema
        if columns is not None:
            schema = pa.schema([schema.field(name) for name in columns])
        # The adapter tags a `geometry` column; a projection need not have one.
        if schema.get_field_index("geometry") >= 0:
            schema = geoarrow_schema_adapter(schema)
        return pa.RecordBatchReader.from_batches(schema, non_empty_batches)

    except Exception as e:
        print(f"Error reading dataset: {e}", file=sys.stderr)
        return None


def _scan_batches(dataset, filter_expr, columns, post_filters):
    """Scan `dataset`, apply post-scan filters, and project to `columns`."""
    scan_columns = columns
    if columns is not None and post_filters:
        scan_columns = list(dict.fromkeys(columns + post_filter_fields(post_filters)))
    batches = dataset.to_batches(
        columns=scan_columns,
        filter=filter_expr,
        use_threads=True,
        batch_readahead=16,
        fragment_readahead=4,
    )
    if not post_filters:
        return batches
    filtered = (apply_post_filters(b, post_filters) for b in batches)
    if scan_columns == columns:
        return filtered
    return (b.select(columns) for b in filtered)


def _prepare_query(
    overture_type,
    bbox: BBox | tuple[float, float, float, float] | list[float] | None = None,
    release=None,
    connect_timeout=None,
    request_timeout=None,
    stac=False,
    where_filters=None,
) -> Optional[Tuple[ds.Dataset, Optional[pc.Expression], List[ParsedFilter]]]:
    """
    Resolve the S3 dataset and filters for a given query.

    Returns the dataset, the filter expression the scan pushes down, and the
    filters to apply after the scan, or None if STAC reports no files
    intersect the bbox.
    """
    if release is None:
        release = get_latest_release()
    path = _dataset_path(overture_type, release)
    bbox_obj = _coerce_bbox(bbox)

    intersecting_files = None
    if bbox_obj and stac:
        intersecting_files = _get_files_from_stac(
            type_theme_map[overture_type], overture_type, bbox_obj, release
        )
        if intersecting_files is not None and len(intersecting_files) == 0:
            return None

    filter_expr = None
    if bbox_obj:
        xmin, ymin, xmax, ymax = bbox_obj.as_tuple()
        filter_expr = (
            (pc.field("bbox", "xmin") < xmax)
            & (pc.field("bbox", "xmax") > xmin)
            & (pc.field("bbox", "ymin") < ymax)
            & (pc.field("bbox", "ymax") > ymin)
        )

    dataset = ds.dataset(
        intersecting_files if intersecting_files is not None else path,
        filesystem=fs.S3FileSystem(
            anonymous=True,
            region="us-west-2",
            connect_timeout=connect_timeout,
            request_timeout=request_timeout,
        ),
    )

    post_filters = []
    if where_filters:
        attr_expr, post_filters = combine(list(where_filters), dataset.schema)
        if attr_expr is not None:
            filter_expr = attr_expr if filter_expr is None else filter_expr & attr_expr

    return dataset, filter_expr, post_filters


def count_rows(
    overture_type,
    bbox=None,
    release=None,
    connect_timeout=None,
    request_timeout=None,
    stac=False,
    where_filters=None,
) -> int:
    """Return the number of rows matching the given parameters."""
    result = _prepare_query(
        overture_type, bbox, release, connect_timeout, request_timeout, stac,
        where_filters=where_filters,
    )
    if result is None:
        return 0
    dataset, filter_expr, post_filters = result
    if not post_filters:
        return dataset.count_rows(filter=filter_expr)
    # count_rows(filter=) cannot apply post-scan filters, so stream and sum,
    # reading only the fields those filters need.
    batches = _scan_batches(dataset, filter_expr, post_filter_fields(post_filters), post_filters)
    return sum(b.num_rows for b in batches)



def record_batch_reader(
    overture_type,
    bbox=None,
    release=None,
    connect_timeout=None,
    request_timeout=None,
    stac=False,
    where_filters=None,
    columns=None,
) -> Optional[pa.RecordBatchReader]:
    """Return a pyarrow RecordBatchReader for the desired bounding box and s3 path, or None on error."""
    result = _prepare_query(
        overture_type, bbox, release, connect_timeout, request_timeout, stac,
        where_filters=where_filters,
    )
    if result is None:
        return None
    dataset, filter_expr, post_filters = result
    return _record_batch_reader_from_dataset(
        dataset, filter_expr=filter_expr, columns=columns, post_filters=post_filters)


def geodataframe(
    overture_type: str,
    bbox: BBox | tuple[float, float, float, float] | list[float] | None = None,
    release: str = None,
    connect_timeout: int = None,
    request_timeout: int = None,
    stac: bool = False,
) -> GeoDataFrame:
    """
    Loads geoparquet for specified type into a geopandas dataframe

    Parameters
    ----------
    overture_type: type to load
    bbox: optional bounding box for data fetch (xmin, ymin, xmax, ymax)
    connect_timeout: optional connection timeout in seconds
    request_timeout: optional request timeout in seconds

    Returns
    -------
    GeoDataFrame with the optionally filtered theme data

    """
    if not HAS_GEOPANDAS:
        raise ImportError("geopandas is required to use this function")

    reader = record_batch_reader(
        overture_type,
        bbox=bbox,
        release=release,
        connect_timeout=connect_timeout,
        request_timeout=request_timeout,
        stac=stac,
    )
    return GeoDataFrame.from_arrow(reader)


def geoarrow_schema_adapter(schema: pa.Schema) -> pa.Schema:
    """
    Convert a geoarrow-compatible schema to a proper geoarrow schema

    This assumes there is a single "geometry" column with WKB formatting

    Parameters
    ----------
    schema: pa.Schema

    Returns
    -------
    pa.Schema
    A copy of the input schema with the geometry field replaced with
    a new one with the proper geoarrow ARROW:extension metadata

    """
    geometry_field_index = schema.get_field_index("geometry")
    geometry_field = schema.field(geometry_field_index)
    geoarrow_geometry_field = geometry_field.with_metadata(
        {b"ARROW:extension:name": b"geoarrow.wkb"}
    )

    geoarrow_schema = schema.set(geometry_field_index, geoarrow_geometry_field)

    return geoarrow_schema


type_theme_map = {
    "address": "addresses",
    "bathymetry": "base",
    "building": "buildings",
    "building_part": "buildings",
    "division": "divisions",
    "division_area": "divisions",
    "division_boundary": "divisions",
    "place": "places",
    "segment": "transportation",
    "connector": "transportation",
    "infrastructure": "base",
    "land": "base",
    "land_cover": "base",
    "land_use": "base",
    "water": "base",
}


def _dataset_path(overture_type: str, release: str) -> str:
    """
    Returns the s3 path of the Overture dataset to use. This assumes overture_type has
    been validated, e.g. by the CLI

    """
    # Map of sub-partition "type" to parent partition "theme" for forming the
    # complete s3 path. Could be discovered by reading from the top-level s3
    # location but this allows to only read the files in the necessary partition.
    theme = type_theme_map[overture_type]
    return (
        f"overturemaps-us-west-2/release/{release}/theme={theme}/type={overture_type}/"
    )


def get_all_overture_types() -> List[str]:
    return list(type_theme_map.keys())


# Registry manifest is now part of the STAC catalog
# Access via catalog.json -> registry property -> manifest field


def _binary_search_manifest(
    manifest_tuples: List[Tuple[str, str]], gers_id: str
) -> Optional[str]:
    """
    Binary search through manifest tuples to find the file containing the given GERS ID.

    Parameters
    ----------
    manifest_tuples: List of (filename, max_id) tuples, sorted by max_id
    gers_id: The GERS ID to search for (lowercase)

    Returns
    -------
    Filename containing the ID, or None if not found
    """
    left, right = 0, len(manifest_tuples) - 1

    while left <= right:
        mid = (left + right) // 2
        filename, max_id = manifest_tuples[mid]

        if gers_id <= max_id:
            # Check if this is the first file where max_id >= gers_id
            if mid == 0 or manifest_tuples[mid - 1][1] < gers_id:
                return filename
            else:
                # Search in the left half
                right = mid - 1
        else:
            # Search in the right half
            left = mid + 1

    return None


def query_gers_registry(gers_id: str) -> Optional[Tuple[str, BBox | None]]:
    """
    Query the GERS registry to get the filepath and bbox for a given GERS ID.

    The registry always uses the latest release.

    Parameters
    ----------
    gers_id: The GERS ID to look up

    Returns
    -------
    Tuple of (filepath, bbox) where bbox is a BBox, or None if not found
    """
    import sys

    release = get_latest_release()
    release_path = f"overturemaps-us-west-2/release/{release}"
    gers_id_lower = gers_id.lower()

    try:
        # Get the cached STAC catalog
        catalog = _get_stac_catalog()

        # Get the registry object from the catalog
        registry = catalog.get("registry")
        if registry is None:
            print("Registry configuration not found in STAC catalog", file=sys.stderr)
            return None

        # The registry contains 'path' and 'manifest'
        # manifest is a list of [filename, max_id] tuples
        registry_path = registry.get("path", "")
        manifest_tuples = registry.get("manifest", [])

        if not manifest_tuples:
            print("Registry manifest is empty in STAC catalog", file=sys.stderr)
            return None

        # Use binary search to find the file containing this GERS ID
        registry_file = _binary_search_manifest(manifest_tuples, gers_id_lower)

        if registry_file is None:
            print(f"{gers_id} does not exist in the GERS Registry.", file=sys.stderr)
            return None

        # Read the specific registry file with filter (predicate pushdown)
        # This only reads the relevant row groups instead of the entire file
        registry_path = f"overturemaps-us-west-2/registry/{registry_file}"
        filesystem = fs.S3FileSystem(anonymous=True, region="us-west-2")

        # Use filters parameter for predicate pushdown
        filtered_table = pq.read_table(
            registry_path, filesystem=filesystem, filters=[("id", "=", gers_id_lower)]
        )

        if filtered_table.num_rows == 0:
            print(f"{gers_id} does not exist in the GERS Registry.", file=sys.stderr)
            return None

        # Get the first (should be only) result
        row = filtered_table.to_pylist()[0]
        path = row["path"]
        bbox_struct = row.get("bbox")
        version = row.get("version")
        first_seen = row.get("first_seen")
        last_seen = row.get("last_seen")
        last_changed = row.get("last_changed")

        # Check if path is NULL - means feature is not present in current release
        if path is None:
            print(
                f"GERS ID '{gers_id}' found in registry but not present in release {release}",
                file=sys.stderr,
            )
            print(f"  Version: {version}", file=sys.stderr)
            print(f"  First seen: {first_seen}", file=sys.stderr)
            print(f"  Last seen: {last_seen}", file=sys.stderr)
            if last_changed:
                print(f"  Last changed: {last_changed}", file=sys.stderr)
            return None

        # Construct full filepath
        if not path.startswith("/"):
            path = "/" + path
        filepath = f"{release_path}{path}"

        # Extract bbox values if available
        if bbox_struct is not None:
            bbox = BBox(
                xmin=bbox_struct["xmin"],
                ymin=bbox_struct["ymin"],
                xmax=bbox_struct["xmax"],
                ymax=bbox_struct["ymax"],
            )
        else:
            bbox = None

        # Write registry information to stderr
        print(f"Found GERS ID '{gers_id}' in release {release}", file=sys.stderr)
        print(f"  Version: {version}", file=sys.stderr)
        print(f"  Filepath: s3://{filepath}", file=sys.stderr)
        if bbox is not None:
            print(
                f"  Bbox: [{bbox.xmin:.6f}, {bbox.ymin:.6f}, {bbox.xmax:.6f}, {bbox.ymax:.6f}]",
                file=sys.stderr,
            )
        else:
            print(f"  Bbox: None", file=sys.stderr)
        print(f"  First seen: {first_seen}", file=sys.stderr)
        print(f"  Last seen: {last_seen}", file=sys.stderr)
        if last_changed:
            print(f"  Last changed: {last_changed}", file=sys.stderr)

        return (filepath, bbox)

    except Exception as e:
        print(f"Error querying GERS registry: {e}", file=sys.stderr)
        return None


def record_batch_reader_from_gers(
    gers_id: str,
    connect_timeout: int = None,
    request_timeout: int = None,
    registry_result: Optional[Tuple[str, BBox | None]] = None,
) -> Optional[pa.RecordBatchReader]:
    """
    Return a pyarrow RecordBatchReader for a specific GERS ID.

    The registry always uses the latest release.

    Parameters
    ----------
    gers_id: The GERS ID to look up
    connect_timeout: Optional connection timeout in seconds
    request_timeout: Optional request timeout in seconds
    registry_result: Optional pre-fetched registry result (filepath, bbox)
                    to avoid duplicate registry queries

    Returns
    -------
    RecordBatchReader with the feature data, or None if not found
    """
    # Use pre-fetched result if provided, otherwise query the registry
    if registry_result is None:
        result = query_gers_registry(gers_id)
        if result is None:
            return None
    else:
        result = registry_result

    filepath, bbox = result

    # Build filter expression based on ID and bbox (if available)
    filter_expr = pc.field("id") == gers_id.lower()

    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox.as_tuple()
        bbox_filter = (
            (pc.field("bbox", "xmin") == xmin)
            & (pc.field("bbox", "ymin") == ymin)
            & (pc.field("bbox", "xmax") == xmax)
            & (pc.field("bbox", "ymax") == ymax)
        )
        filter_expr = filter_expr & bbox_filter

    try:
        dataset = ds.dataset(
            filepath,
            filesystem=fs.S3FileSystem(
                anonymous=True,
                region="us-west-2",
                connect_timeout=connect_timeout,
                request_timeout=request_timeout,
            ),
        )
    except Exception as e:
        print(f"Error opening dataset for GERS ID '{gers_id}': {e}", file=sys.stderr)
        return None
    return _record_batch_reader_from_dataset(dataset, filter_expr=filter_expr)
