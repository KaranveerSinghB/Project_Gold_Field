import pandas as pd
import folium
from folium.plugins import HeatMap, MousePosition
import streamlit as st
from streamlit_folium import st_folium
from streamlit_autorefresh import st_autorefresh
import requests
import math
import numpy as np

PUNJAB_DISTRICTS = {
    "Amritsar": (31.63, 74.87), "Barnala": (30.38, 75.54), "Bathinda": (30.21, 74.94),
    "Faridkot": (30.67, 74.75), "Fatehgarh Sahib": (30.64, 76.39), "Fazilka": (30.40, 74.02),
    "Ferozepur": (30.92, 74.61), "Gurdaspur": (32.04, 75.40), "Hoshiarpur": (31.52, 75.91),
    "Jalandhar": (31.32, 75.57), "Kapurthala": (31.38, 75.38), "Ludhiana": (30.90, 75.85),
    "Malerkotla": (30.52, 75.88), "Mansa": (29.98, 75.38), "Moga": (30.81, 75.17),
    "Pathankot": (32.26, 75.64), "Patiala": (30.33, 76.38), "Rupnagar": (30.96, 76.53),
    "SAS Nagar (Mohali)": (30.70, 76.71), "SBS Nagar": (31.12, 76.11), "Sangrur": (30.24, 75.84),
    "Sri Muktsar Sahib": (30.48, 74.51), "Tarn Taran": (31.45, 74.92)
}

def get_closest_district(lat, lon):
    distances = {}
    min_dist = float('inf')
    
    for district, (d_lat, d_lon) in PUNJAB_DISTRICTS.items():
        dist = math.sqrt((lat - d_lat)**2 + (lon - d_lon)**2)
        distances[district] = dist
        if dist < min_dist:
            min_dist = dist
            
    assigned_districts = []
    for district, dist in distances.items():
        if dist <= min_dist + 0.15:
            assigned_districts.append(district)
            
    return ", ".join(assigned_districts)

# Streamlit Page Configuration
st.set_page_config(page_title="Punjab Fire Tracker", layout="wide", initial_sidebar_state="expanded")

hide_st_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
"""
st.markdown(hide_st_style, unsafe_allow_html=True)

@st.cache_data(ttl=3600)
def fetch_punjab_fires(api_key):
    source = 'VIIRS_SNPP_NRT'
    area_coords = '73.8,29.5,76.9,32.5'
    day_range = '1'
    
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{api_key}/{source}/{area_coords}/{day_range}"
    
    try:
        fire_data = pd.read_csv(url)
        
        if fire_data.empty:
            return None
            
        confidence_mapping = {'h': 'High', 'n': 'Nominal', 'l': 'Low'}
        fire_data['confidence'] = fire_data['confidence'].map(confidence_mapping)
        
        filtered_fires = fire_data[fire_data['confidence'].isin(['High', 'Nominal', 'Low'])].copy()
        
        # Geofence Exclusion Zone
        # Drop fires where Latitude strictly > 31.0 AND Longitude strictly < 74.5
        exclusion_mask = (filtered_fires['latitude'] > 31.0) & (filtered_fires['longitude'] < 74.5)
        filtered_fires = filtered_fires[~exclusion_mask]
        
        if filtered_fires.empty:
            return None
            
        # Add District column
        filtered_fires['District'] = filtered_fires.apply(
            lambda row: get_closest_district(row['latitude'], row['longitude']), axis=1
        )
        
        # Time formatting
        filtered_fires['acq_time'] = filtered_fires['acq_time'].astype(str).str.zfill(4)
        datetime_strings = filtered_fires['acq_date'] + ' ' + filtered_fires['acq_time']
        utc_times = pd.to_datetime(datetime_strings, format='%Y-%m-%d %H%M').dt.tz_localize('UTC')
        ist_times = utc_times.dt.tz_convert('Asia/Kolkata')
        filtered_fires['time_ist'] = ist_times.dt.strftime('%Y-%m-%d %I:%M %p')
        
        # Convert confidence to categorical for proper sorting
        confidence_order = pd.CategoricalDtype(categories=['High', 'Nominal', 'Low'], ordered=True)
        filtered_fires['confidence'] = filtered_fires['confidence'].astype(confidence_order)
        
        # Sort by confidence (High first) and then by Intensity (FRP)
        sorted_fires = filtered_fires.sort_values(
            by=['confidence', 'frp'], 
            ascending=[True, False]
        )
        
        return sorted_fires
        
    except Exception as e:
        st.error(f"An error occurred while fetching data: {e}")
        return None

def map_fires(df, center_coords=[31.1471, 75.3412], zoom_level=8):
    if df is None or df.empty:
        return None

    # Initialize map (Defaults to OpenStreetMap)
    punjab_map = folium.Map(location=center_coords, zoom_start=zoom_level)

    # Add Google Satellite as an optional layer
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google',
        name='Google Satellite',
        overlay=False,
        control=True
    ).add_to(punjab_map)

    # Add Mouse Position tool to see coordinates as you move the pointer
    MousePosition(
        position='topright',
        separator=' | ',
        empty_string='NaN',
        lng_first=False,
        prefix='Coordinates:'
    ).add_to(punjab_map)

    # Add Click-to-Coordinate tool
    folium.LatLngPopup().add_to(punjab_map)

    # Add HeatMap
    heat_data = [[row['latitude'], row['longitude']] for index, row in df.iterrows()]
    HeatMap(heat_data, radius=15).add_to(punjab_map)

    # Add CRITICAL priority markers
    critical_fires = df[df['Response Priority'] == '🚨 Priority 1: CRITICAL']
    for index, row in critical_fires.iterrows():
        gmaps_link = f"https://www.google.com/maps?q={row['latitude']},{row['longitude']}"
        popup_text = f"<b>District:</b> {row.get('District', 'Unknown')}<br><b>Priority:</b> CRITICAL<br><b>Intensity (FRP):</b> {row['frp']}<br><b>Time:</b> {row['time_ist']}<br><a href='{gmaps_link}' target='_blank'>View Location</a>"
        
        folium.Marker(
            location=[row['latitude'], row['longitude']],
            popup=folium.Popup(popup_text, max_width=300),
            icon=folium.Icon(color='red', icon='fire')
        ).add_to(punjab_map)

    # Add Layer Control
    folium.LayerControl(position='bottomleft').add_to(punjab_map)

    return punjab_map

MY_NASA_KEY = st.secrets["NASA_API_KEY"]

def send_telegram_alert(message, chat_id):
    bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN")
    if not bot_token or not chat_id:
        return
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

def main():
    st.title("Punjab Active Fire Tracker")
    
    # Refresh the page every 1 hour (3600000 milliseconds)
    st_autorefresh(interval=3600000, key="data_refresh")
    
    with st.spinner("Fetching latest satellite data..."):
        active_fires = fetch_punjab_fires(MY_NASA_KEY)
        
    if active_fires is not None and not active_fires.empty:
        # Sidebar Configuration
        st.sidebar.markdown("<h2 style='margin-top:-30px;'>Project Gold Field</h2>", unsafe_allow_html=True)
        
        st.sidebar.header("Filters")
        
        critical_threshold = st.sidebar.slider(
            "Critical Alert Threshold (FRP)", 
            min_value=10.0, 
            max_value=50.0, 
            value=15.0, 
            help="Adjust the minimum heat intensity for Priority 1 alerts. Default is 15.0 for early detection of wheat field fires."
        )
        
        district_options = ["All of Punjab"] + list(PUNJAB_DISTRICTS.keys())
        selected_district = st.sidebar.selectbox("Select District", district_options)
            
        # Apply District Filter
        if selected_district != "All of Punjab":
            display_fires = active_fires[active_fires['District'].str.contains(selected_district, na=False, regex=False)].copy()
        else:
            display_fires = active_fires.copy()
            
        if display_fires.empty:
            st.warning("No fires found for the selected filters.")
            st.stop()

        # Priority Logic
        conditions = [
            display_fires['frp'] >= critical_threshold,
            (display_fires['frp'] >= 10) & (display_fires['confidence'] == 'High'),
            (display_fires['frp'] >= 15) & (display_fires['confidence'] == 'Nominal')
        ]
        choices = [
            '🚨 Priority 1: CRITICAL',
            '🟠 Priority 2: HIGH',
            '🟠 Priority 2: HIGH'
        ]
        display_fires['Response Priority'] = np.select(conditions, choices, default='🟡 Priority 3: MONITOR')
        priority_order = pd.CategoricalDtype(categories=['🚨 Priority 1: CRITICAL', '🟠 Priority 2: HIGH', '🟡 Priority 3: MONITOR'], ordered=True)
        display_fires['Response Priority'] = display_fires['Response Priority'].astype(priority_order)

        # Telegram Alert Logic
        if 'alerted_fires' not in st.session_state:
            st.session_state['alerted_fires'] = set()

        critical_fires = display_fires[display_fires['Response Priority'] == '🚨 Priority 1: CRITICAL']
        
        admin_id = st.secrets.get("TELEGRAM_ADMIN_ID")

        officer_roster = {
            "Amritsar": st.secrets.get("CHAT_ID_AMRITSAR"),
            "Barnala": st.secrets.get("CHAT_ID_BARNALA"),
            "Bathinda": st.secrets.get("CHAT_ID_BATHINDA"),
            "Faridkot": st.secrets.get("CHAT_ID_FARIDKOT"),
            "Fatehgarh Sahib": st.secrets.get("CHAT_ID_FATEHGARH_SAHIB"),
            "Fazilka": st.secrets.get("CHAT_ID_FAZILKA"),
            "Ferozepur": st.secrets.get("CHAT_ID_FEROZEPUR"),
            "Gurdaspur": st.secrets.get("CHAT_ID_GURDASPUR"),
            "Hoshiarpur": st.secrets.get("CHAT_ID_HOSHIARPUR"),
            "Jalandhar": st.secrets.get("CHAT_ID_JALANDHAR"),
            "Kapurthala": st.secrets.get("CHAT_ID_KAPURTHALA"),
            "Ludhiana": st.secrets.get("CHAT_ID_LUDHIANA"),
            "Malerkotla": st.secrets.get("CHAT_ID_MALERKOTLA"),
            "Mansa": st.secrets.get("CHAT_ID_MANSA"),
            "Moga": st.secrets.get("CHAT_ID_MOGA"),
            "Pathankot": st.secrets.get("CHAT_ID_PATHANKOT"),
            "Patiala": st.secrets.get("CHAT_ID_PATIALA"),
            "Rupnagar": st.secrets.get("CHAT_ID_RUPNAGAR"),
            "SAS Nagar (Mohali)": st.secrets.get("CHAT_ID_SAS_NAGAR"),
            "SBS Nagar": st.secrets.get("CHAT_ID_SBS_NAGAR"),
            "Sangrur": st.secrets.get("CHAT_ID_SANGRUR"),
            "Sri Muktsar Sahib": st.secrets.get("CHAT_ID_SRI_MUKTSAR_SAHIB"),
            "Tarn Taran": st.secrets.get("CHAT_ID_TARN_TARAN")
        }
        
        for index, row in critical_fires.iterrows():
            # Use coordinates and time as a unique identifier
            fire_id = f"{row['latitude']}_{row['longitude']}_{row['time_ist']}"
            
            if fire_id not in st.session_state['alerted_fires']:
                gmaps_link = f"https://www.google.com/maps?q={row['latitude']},{row['longitude']}"
                
                message = (
                    f"🚨 *URGENT: CRITICAL FIELD FIRE DETECTED*\n\n"
                    f"📍 *District:* {row.get('District', 'Unknown')}\n"
                    f"🔥 *Heat Intensity (FRP):* {row['frp']}\n"
                    f"🕒 *Time:* {row['time_ist']}\n\n"
                    f"🗺️ *Action:* [View on Google Maps]({gmaps_link})"
                )
                
                districts_involved = row.get('District', '').split(', ')

                # Route to specific officers
                for dist in districts_involved:
                    target_id = officer_roster.get(dist)
                    if target_id: 
                        send_telegram_alert(message, target_id)

                # Always send a master copy to the Admin
                if admin_id:
                    send_telegram_alert(message, admin_id)

                st.session_state['alerted_fires'].add(fire_id)

        # Calculate display time range
        display_time_series = pd.to_datetime(display_fires['time_ist'], format='%Y-%m-%d %I:%M %p')
        min_time = display_time_series.min().strftime('%b %d, %Y %I:%M %p')
        max_time = display_time_series.max().strftime('%b %d, %Y %I:%M %p')
        
        # Sidebar Stats
        st.sidebar.header("Fire Statistics")
        st.sidebar.metric("Total Active Fires", len(display_fires), help="Total heat anomalies detected by VIIRS satellite in this window.")
        st.sidebar.metric("CRITICAL Alerts (Priority 1)", len(display_fires[display_fires['Response Priority'] == '🚨 Priority 1: CRITICAL']), help="Guaranteed fires with 80-100% certainty.")
        st.sidebar.metric("HIGH Alerts (Priority 2)", len(display_fires[display_fires['Response Priority'] == '🟠 Priority 2: HIGH']), help="Likely fires. Note: Large blazes often appear as 'Nominal' due to heavy smoke.")
        
        st.sidebar.markdown("---")
        st.sidebar.info(f"Showing fire data from **{min_time}** to **{max_time}** (IST)")
        
        # Map
        st.subheader(f"Interactive Fire Map - {selected_district}")
        
        # Determine center and zoom level based on selection
        if selected_district == "All of Punjab":
            center_coords = [31.1471, 75.3412]
            zoom_level = 8
        else:
            center_coords = PUNJAB_DISTRICTS[selected_district]
            zoom_level = 10
            
        punjab_map = map_fires(display_fires.head(500), center_coords=center_coords, zoom_level=zoom_level)
        if punjab_map:
            st_folium(punjab_map, width="stretch", height=600)
            
        # District Leaderboard
        st.subheader("Fires by District")
        # Split fuzzy districts for accurate bar chart counting
        exploded_districts = active_fires['District'].str.split(', ').explode()
        district_counts = exploded_districts.value_counts()
        st.bar_chart(district_counts)
            
        # Dynamic Table Limits
        display_fires_sorted = display_fires.sort_values(by=['Response Priority', 'frp'], ascending=[True, False])
        
        important_columns = ['District', 'latitude', 'longitude', 'Response Priority', 'frp', 'time_ist']
        
        display_df = display_fires_sorted[important_columns].rename(columns={
            'latitude': 'Latitude',
            'longitude': 'Longitude',
            'frp': 'Fire Radiative Power',
            'time_ist': 'Time (IST)'
        })
        
        # Add Google Maps link column
        display_df['Google Maps'] = display_df.apply(lambda row: f"https://www.google.com/maps?q={row['Latitude']},{row['Longitude']}", axis=1)
        
        # Configure columns
        column_config = {
            "Fire Radiative Power": st.column_config.NumberColumn(width="small"),
            "Google Maps": st.column_config.LinkColumn(width="medium")
        }
        
        if selected_district == "All of Punjab":
            st.subheader("Top 15 Most Intense Field Fires - All of Punjab")
            st.dataframe(display_df.head(15), use_container_width=True, hide_index=True, column_config=column_config)
        else:
            st.subheader(f"All Field Fires - {selected_district}")
            st.dataframe(display_df, use_container_width=True, hide_index=True, column_config=column_config)
    else:
        st.info("No active fires detected in the specified region at this time.")

if __name__ == "__main__":
    main()
