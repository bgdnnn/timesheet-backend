import os
import re
import httpx
import argparse

# Setup pattern to match your files
# Example: Payslip for Tax Week_32 Tax Year_2020-2021.pdf
PATTERN = re.compile(r"Payslip for Tax Week_(\d+) Tax Year_(\d{4})-(\d{4})\.pdf", re.IGNORECASE)

async def bulk_upload(folder_path, api_url, token):
    if not os.path.exists(folder_path):
        print(f"Error: Folder {folder_path} does not exist.")
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        for filename in os.listdir(folder_path):
            if not filename.lower().endswith(".pdf"):
                continue

            match = PATTERN.search(filename)
            if not match:
                print(f"Skipping {filename} (doesn't match format)")
                continue

            week = match.group(1)
            start_year = match.group(2) # e.g. 2020
            end_year = match.group(3)   # e.g. 2021

            # Convert 2020-2021 to 20-21
            tax_year = f"{start_year[2:]}-{end_year[2:]}"
            
            file_path = os.path.join(folder_path, filename)
            
            print(f"Uploading Week {week}, Year {tax_year}...")

            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/pdf")}
                data = {
                    "tax_week": week,
                    "tax_year": tax_year
                }
                headers = {"Authorization": f"Bearer {token}"}
                
                try:
                    response = await client.post(
                        f"{api_url}/payslip-files/upload",
                        data=data,
                        files=files,
                        headers=headers
                    )
                    if response.status_code == 200:
                        print(f"✅ Successfully uploaded {filename}")
                    else:
                        print(f"❌ Failed to upload {filename}: {response.status_code} - {response.text}")
                except Exception as e:
                    print(f"❌ Error uploading {filename}: {e}")

if __name__ == "__main__":
    import asyncio
    parser = argparse.ArgumentParser(description="Bulk upload payslips to Timesheet App")
    parser.add_argument("--folder", required=True, help="Path to folder containing PDF files")
    parser.add_argument("--url", default="https://timesheet.home-clouds.com/api", help="API Base URL")
    parser.add_argument("--token", required=True, help="Your API Token (ts_token from localStorage)")
    
    args = parser.parse_args()
    
    # Remove trailing slash from URL
    url = args.url.rstrip("/")
    
    asyncio.run(bulk_upload(args.folder, url, args.token))
