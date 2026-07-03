#!/usr/bin/env python
"""
CAISO LMP Node Shapefile Generator
Developed by Greg Miller, grmiller@ucdavis.edu
Refactored and Modernized in July 2026

Purpose: To create a shapefile and CSV file of Locational Marginal Pricing (LMP) Nodes
in CAISO and most of WECC using CAISO price contour map data:
http://wwwmobile.caiso.com/Web.Service.Chart/pricecontourmap.html
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import geopandas as gpd
import pandas as pd
import requests

# Global constants
DEFAULT_PRICE_MAP_URL = (
    "http://wwwmobile.caiso.com/Web.Service.Chart/api/v3/ChartService/PriceContourMap1"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def get_lmp_loc(
    url: str = DEFAULT_PRICE_MAP_URL, timeout: int = 15, max_retries: int = 3
) -> List[Dict[str, Any]]:
    """
    Fetches LMP node location data from CAISO's Price Contour Map endpoint.

    Returns:
        List of dictionaries containing node data. Each dictionary has keys:
        - 'node_id': name of the node
        - 'latitude': latitude float
        - 'longitude': longitude float
        - 'area': control area string
        - 'node_type': node type string (e.g. LOAD, GEN)
    """
    headers = {"User-Agent": USER_AGENT}
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Fetching LMP data from: {url} (Attempt {attempt}/{max_retries})")
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            json_obj = response.json()
            
            # Navigate the JSON structure to get node entries
            # Expected structure: json_obj['l'][2]['m']
            if 'l' not in json_obj or len(json_obj['l']) <= 2 or 'm' not in json_obj['l'][2]:
                raise ValueError("Unexpected JSON response structure from CAISO API.")
                
            node_entries = json_obj['l'][2]['m']
            logger.info(f"Successfully retrieved {len(node_entries)} node entries.")
            
            return_list = [
                {
                    'node_id': str(entry['n']),
                    'latitude': float(entry['c'][0]),
                    'longitude': float(entry['c'][1]),
                    'area': str(entry['a']),
                    'node_type': str(entry['p'])
                }
                for entry in node_entries
                if 'n' in entry and 'c' in entry and len(entry['c']) >= 2
            ]
            
            return return_list
            
        except requests.RequestException as e:
            logger.warning(f"Network error on attempt {attempt}: {e}")
            if attempt == max_retries:
                raise
            time.sleep(2)
        except (ValueError, KeyError, IndexError) as e:
            logger.error(f"Data parsing error on attempt {attempt}: {e}")
            raise


def save_to_csv(data: List[Dict[str, Any]], output_path: Path) -> None:
    """Saves node data to a CSV file with predefined column ordering."""
    logger.info(f"Saving CSV file to {output_path}")
    df = pd.DataFrame(data)
    
    # Reorder columns to match original: area, latitude, longitude, node_id, node_type
    column_order = ['area', 'latitude', 'longitude', 'node_id', 'node_type']
    df = df.reindex(columns=column_order)
    
    # Create parent directories if they don't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, lineterminator='\n')
    logger.info("CSV file saved successfully.")


def save_to_shapefile(data: List[Dict[str, Any]], output_path: Path) -> None:
    """
    Saves node data to an ESRI Shapefile using GeoPandas.
    Sets the CRS to EPSG:4326 (WGS84).
    """
    logger.info(f"Saving Shapefile to {output_path}")
    df = pd.DataFrame(data)
    
    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df['longitude'], df['latitude']),
        crs="EPSG:4326"
    )
    
    # Match original shapefile schema attributes: AREA, NODE_ID, TYPE
    gdf_shp = gdf[['area', 'node_id', 'node_type', 'geometry']].rename(
        columns={
            'area': 'AREA',
            'node_id': 'NODE_ID',
            'node_type': 'TYPE'
        }
    )
    
    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save using pyogrio engine for speed
    gdf_shp.to_file(output_path, driver="ESRI Shapefile", engine="pyogrio")
    logger.info("Shapefile saved successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch CAISO LMP Nodes and save as CSV and/or Shapefile."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_PRICE_MAP_URL,
        help="CAISO Price Contour Map API endpoint URL."
    )
    parser.add_argument(
        "-o", "--output-csv",
        type=Path,
        default=Path("LMP_coordinates.csv"),
        help="Path to output the CSV file (default: LMP_coordinates.csv)."
    )
    parser.add_argument(
        "-s", "--output-shp",
        type=Path,
        default=Path("LMP/caiso_lmp.shp"),
        help="Path to output the shapefile (default: LMP/caiso_lmp.shp)."
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Disable CSV generation."
    )
    parser.add_argument(
        "--no-shp",
        action="store_true",
        help="Disable Shapefile generation."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging."
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        
    if args.no_csv and args.no_shp:
        logger.error("Both CSV and Shapefile output disabled. Nothing to do.")
        sys.exit(1)
        
    try:
        data = get_lmp_loc(url=args.url)
        
        if not args.no_csv:
            save_to_csv(data, args.output_csv)
            
        if not args.no_shp:
            save_to_shapefile(data, args.output_shp)
            
        logger.info("Processing completed successfully.")
        
    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
