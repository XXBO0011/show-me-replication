
# %% Collect annual report links
# Construct annual report visual measures for the S&P 1500 sample.
#
# Main inputs
#   sp1500_raw.csv          S&P 1500 tickers and Compustat GVKEYs
#   Stocklight              Company listings and links to annual report PDFs
#   combined_annotations.csv and images/   Annotated crops for fine-tuning
#
# Main outputs
#   sp1500_stocklight_pdf_urls_v4.csv   Report links and firm identifiers
#   regions.csv                        Detected regions and crop paths
#   classified.csv                     Predicted class and score for each crop
#   page_category.csv                  Dominant visual class per page with a retained crop
#   company_year_counts.csv            Page counts by firm, report year, and visual class
#   siglip_finetuned/                   Model checkpoint and evaluation files

import subprocess
import json
import time
from urllib.parse import urlsplit
import pandas as pd  
import re
from pathlib import Path
Source = "https://stocklight.com/stocks/us/annual-reports?sort_by=alpha"
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"
INPUT = ROOT / "sp1500_raw.csv"
OUTPUT = ROOT / "sp1500_stocklight_pdf_urls_v4.csv"

# Evaluate a JavaScript expression in the active Chrome tab through AppleScript.
# js is the expression. retries is the maximum number of attempts on a timeout.
# Return the result as stripped text.
def chrome_js(js, retries=1):
    script = ('tell application "Google Chrome" to ''execute active tab of front window javascript '+ json.dumps(js))
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True,
                timeout=45
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            if attempt == retries:
                raise
            print(f"Chrome has not returned a result. Retrying in 5 seconds ({attempt + 1}/{retries}).")
            time.sleep(5)
        except subprocess.CalledProcessError as error:
            print("AppleScript error details:", error.stderr)
            raise


# Poll the active tab until the JavaScript condition evaluates to true.
# condition is an expression that tests the expected page state.
def wait_for_page(condition):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = chrome_js(f"({condition}) ? 'READY' : 'WAIT'",retries=3)
        if status == "READY":
            return
        time.sleep(1)
    raise TimeoutError("The page is not ready. Check the active tab in Chrome.")
# Open the URL in the same tab used for JavaScript queries.
def open_url(url):
    script = ('tell application "Google Chrome" to ''set URL of active tab of front window to '+ json.dumps(url))
    subprocess.run(["osascript", "-e", script],capture_output=True,text=True,check=True,timeout=45)

    time.sleep(5)
subprocess.run(["open", "-a", "Google Chrome", Source])
# Identify the company detail links labeled "More".
more_js = ("Array.from(document.querySelectorAll('a[href]'))"".filter(a => a.textContent.trim().toLowerCase() === 'more')")
# Match the listing against normalized S&P 1500 tickers.
SP1500 = pd.read_csv(INPUT, dtype=str, keep_default_na=False)
target_tics = set(SP1500["tic"].str.strip().str.upper().str.replace(".", "-", regex=False))
records = []
list_url = Source
# Limit the number of company listing pages processed in this run.
max_pages = 2
pages_done = 0

while list_url is not None:
    # Wait for the expected listing URL and company links before collecting records.
    for attempt in range(1, 4):
        try:
            wait_for_page(f"location.href === {json.dumps(list_url)}"f" && ({more_js}).length > 0")
            break
        except TimeoutError:
            # Retry the listing when the site shows "Retry later".
            text = chrome_js("document.title + ' ' + ""(document.body ? document.body.innerText : '')").lower()
            if "retry later" not in text:
                raise
            if attempt == 3:
                raise TimeoutError(f'This page repeatedly displayed "Retry later." Try again later: {list_url}')
            # Back off for 60 seconds, then 120 seconds if needed.
            delay = 60 * (2 ** (attempt - 1))
            print(f'The page displayed "Retry later." Reopening the same page in {delay} seconds.')
            time.sleep(delay)
            open_url(list_url)

    # Read company and next-page links before leaving the current listing.
    more_urls = json.loads(chrome_js(f"JSON.stringify(({more_js}).map(a => a.href))"))
    next_links = json.loads(chrome_js("JSON.stringify(Array.from(document.querySelectorAll('a[href]')).filter(a => a.textContent.trim() === '>').map(a => a.href))"))
    next_url = next_links[0] if next_links else None
    for i, url in enumerate(more_urls, start=1):
        # Extract the ticker from the company URL and restrict visits to the target sample.
        company_code = urlsplit(url).path.strip("/").split("/")[2]
        tic = company_code.split("-", 1)[1].upper()
        if tic.replace(".", "-") not in target_tics:
            continue
        print(f"{tic} is in the target sample. Collecting annual report links.")
        records = []
        open_url(url)
        # Confirm that the active tab is on the target company's annual report page.
        wait_for_page(
            f"location.origin === new URL({json.dumps(url)}).origin"
            f" && location.pathname === new URL({json.dumps(url)}).pathname"
            " && document.querySelector('h1')"
            " && document.querySelector('h1').textContent"
            ".toLowerCase().includes('annual reports')"
        )
        # Keep distinct PDF URLs and extract the year from each filename.
        links = json.loads(chrome_js("JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(a => a.href))"))
        pdf_urls=[]
        for link in links:
            if urlsplit(link).path.lower().endswith(".pdf") and link not in pdf_urls:
                pdf_urls.append(link)
        for pdf_url in pdf_urls:
            filename = urlsplit(pdf_url).path.split("/")[-1]
            year_match = re.search(r"-(19\d{2}|20\d{2})-", filename)
            if year_match is None:
                continue
            year = year_match.group(1)
            records.append({"tic": tic, "year": year, "pdf_url": pdf_url})
        df = pd.DataFrame(records, columns=["tic", "year", "pdf_url"])
        if not df.empty:
            # Update the report manifest and deduplicate by ticker and PDF URL.
            df.to_csv(OUTPUT,mode="a",header=not OUTPUT.exists(),index=False,encoding="utf-8" if OUTPUT.exists() else "utf-8-sig")
            all_df = pd.read_csv(OUTPUT, dtype=str, keep_default_na=False, encoding="utf-8-sig")
            all_df = all_df.drop_duplicates(subset=["tic", "pdf_url"])
            all_df.to_csv(OUTPUT, mode="w", index=False, encoding="utf-8-sig")    
        time.sleep(3)
    print("Finished processing the companies on this listing page.")
    pages_done += 1
    list_url = next_url
    if pages_done >= max_pages:
        print(f"Processed {pages_done} listing pages. Stopping collection.")
        break
    list_url = next_url
    time.sleep(3)
    chrome_js(f"location.assign({json.dumps(list_url)}); 'OPENED';")
    print("Next listing page:", list_url)


# %% Attach Compustat GVKEYs to annual report links
# Match the S&P 1500 company list to the report manifest and add a GVKEY column.
import pandas as pd
# Read identifiers as text to preserve leading zeros in GVKEYs.
companies = pd.read_csv(ROOT / "sp1500_raw.csv",dtype=str,keep_default_na=False)
output_file = ROOT / "sp1500_stocklight_pdf_urls_v4.csv"
reports = pd.read_csv(output_file,dtype=str,keep_default_na=False)
# Apply the same ticker normalization to both files before matching.
companies["tic"] = companies["tic"].str.strip().str.upper().str.replace(".", "-", regex=False)
reports["tic"] = reports["tic"].str.strip().str.upper().str.replace(".", "-", regex=False)
# Build a ticker-to-GVKEY crosswalk using nonblank tickers and distinct pairs.
mapping = companies[["tic", "gvkey"]].copy()
mapping = mapping[mapping["tic"] != ""]
mapping = mapping.drop_duplicates(subset=["tic", "gvkey"])
# Keep every report and require at most one crosswalk row per ticker.
reports = reports.merge(mapping,on="tic",how="left",validate="many_to_one")
print("Annual report records:", len(reports))
print("Records without a matching GVKEY:", reports["gvkey"].isna().sum())
reports.to_csv(output_file, index=False, encoding="utf-8-sig")
print("Saved:", output_file)

# %% Read the annual report URL list
from pathlib import Path
import pandas as pds
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"
csv_path = ROOT / "sp1500_stocklight_pdf_urls_v4.csv"
get_PDF_URL = pds.read_csv(csv_path, keep_default_na=False)["pdf_url"]
get_PDF_URL = get_PDF_URL [get_PDF_URL != ""]
#print(get_PDF_URL.head(20))
#print(len(get_PDF_URL))
# for url in get_PDF_URL:  # Read one PDF URL at a time.
    #print(url)

# %% Render annual report PDFs as PNG files
# Use one folder per firm and report year for images and a separate folder for detection results.
year = 2025
PNG_ROOT = ROOT / "annualreport——png"
get_firm = pds.read_csv(csv_path, dtype = str,keep_default_na=False)["gvkey"].drop_duplicates()
for i in get_firm:
    year_folder = PNG_ROOT / f"{year}"
    company_folder = year_folder  / f"{year}_{i}"
    company_folder.mkdir(parents=True, exist_ok=True)
    year_folder_cropped_result = PNG_ROOT / f"{year}_cropped_result"
    year_folder_cropped_result.mkdir(parents=True, exist_ok=True)
    company_result_folder = year_folder_cropped_result/f"{year}_{i}"
    company_result_folder.mkdir(parents=True, exist_ok=True)
import pymupdf
import requests
# Select reports for the configured year with a nonblank PDF URL.
reports = pds.read_csv(csv_path, dtype=str, keep_default_na=False)
reports = reports[(reports["year"].str.strip() == str(year))& (reports["pdf_url"].str.strip() != "")]
for report_number,company in enumerate(reports.to_dict("records"), start=1):
    url = company["pdf_url"]
    gvkey = company["gvkey"]
    print(f"Processing report {report_number}/{len(reports)} (GVKEY: {gvkey})")
    company_folder =  year_folder / f"{year}_{gvkey}"
    # Reuse cached page images if the firm-year folder already contains any PNG.
    if any(company_folder.glob("*.png")):
        print("PNG files already exist. Skipping GVKEY:", gvkey)
        continue
    try:
        response = requests.get(url, timeout=(10, 60))
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        print("Skipping PDF after a download error:", url, error)
        continue
    #response = requests.get(url,timeout = (10,60))
    #response.raise_for_status()
    # Render the downloaded PDF in memory at 200 dpi and write one PNG per page.
    with pymupdf.open(stream = response.content, filetype = "pdf") as doc:
        for page_number, page in enumerate(doc,start = 1):
             pix = page.get_pixmap(dpi=200,alpha=False)
             #print(doc.page_count)
             #print(pix.width,pix.height)
             image_path = company_folder / f"page_{page_number:04d}.png"
             pix.save(str(image_path))

# %% Detect and crop visual regions
# Write annotated images, detection JSON, region crops, and per-page CSVs.
from paddleocr import LayoutDetection
from PIL import Image 
model = LayoutDetection(model_name="PP-DocLayout_plus-L",device="cpu")
company_gvkey = pds.read_csv(csv_path,dtype=str, keep_default_na=False)["gvkey"].drop_duplicates()
fields = [ "year", "gvkey", "page_file", "region_number","label", "score", "crop_path"]
# Use the GVKEY position in the manifest to resume layout detection.
start_company = 150
for company_number, test_gvkey in enumerate(company_gvkey, start=1):
    if company_number < start_company:
        continue
    print(f"Processing company {company_number}/{len(company_gvkey)} (GVKEY: {test_gvkey})")
    test_folder = year_folder / f"{year}_{test_gvkey}"
    image_files = sorted(test_folder.glob("page_*.png"))
    company_result_folder = year_folder_cropped_result / f"{year}_{test_gvkey}"
    company_result_folder.mkdir(parents=True, exist_ok=True)
    for page_path in image_files:
        results = model.predict(str(page_path),batch_size =1 )
        for result in results:
            # Save the detector's annotated image and structured result for the page.
            result.save_to_img(save_path=str(company_result_folder))
            result.save_to_json(save_path=str(company_result_folder / f"{page_path.stem}.json"))
            region_records = []
            # Crop image, chart, and table detections from the original page.
            with Image.open(page_path) as page_image:
                for region_number, box in enumerate(result["boxes"], start=1):
                    if box["label"] in ["image", "chart", "table"]:
                        x1, y1, x2, y2 = map(int, box["coordinate"])
                        cropped_image = page_image.crop((x1, y1, x2, y2))
                        crop_path = company_result_folder / f"{page_path.stem}_{box['label']}_{region_number:03d}.png"
                        cropped_image.save(crop_path)
                        print("Saved:", crop_path)
                        region_records.append({"year": year,"gvkey": test_gvkey,"page_file": page_path.name,
                        "region_number": region_number,"label": box["label"],"score": float(box["score"]),"crop_path": str(crop_path)})
            # Store one record per retained region with its detector score and crop path.
            region_df = pds.DataFrame(region_records,columns=fields)
            records_path = company_result_folder/f"{page_path.stem}_regions.csv"
            region_df.to_csv(records_path, index=False, encoding="utf-8-sig")
# %% Combine page-level region manifests
# Concatenate the per-page CSVs for the selected year and keep GVKEYs as text.
csv_combined_result = sorted(year_folder_cropped_result.glob(f"{year}_*/page_*_regions.csv"))
page_tables = []
for csv_path in csv_combined_result:
    page_df = pds.read_csv(csv_path, dtype={"gvkey": str})
    page_tables.append(page_df)
company_regions = pds.concat(page_tables, ignore_index=True)
summary_path = year_folder_cropped_result / "regions.csv"
company_regions.to_csv(summary_path, index=False, encoding="utf-8-sig")

# %% Split the manually labeled crops
from pathlib import Path
import pandas as pds
import hashlib
from PIL import Image
from sklearn.model_selection import train_test_split
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"
# Read manual labels, drop blank labels, and resolve each sample ID to a crop image.
label_file = ROOT / "combined_annotations.csv"
data = pds.read_csv(label_file, dtype=str,  keep_default_na=False)
data["label"] = data["label"].str.strip()
data = data[data["label"] != ""]
data["sample_id"]=data["sample_id"].str.strip()
image_folder = ROOT/"images"
data["image_path"] = data["sample_id"].map(lambda sample_id:str(image_folder/f"{sample_id}.png"))
# Split the labeled crops into 70% training, 15% validation, and 15% test, stratified by class.
train_data, remaining_data = train_test_split(data,test_size=0.3,random_state=123,stratify=data["label"])
validation_data, test_data = train_test_split(remaining_data,test_size=0.50,random_state=42,stratify=remaining_data["label"])
# Write the split manifests before adding numeric label IDs in memory.
split_folder = label_file.parent / "siglip_splits"
split_folder.mkdir(parents=True, exist_ok=True)
train_data.to_csv(split_folder / "train.csv", index=False, encoding="utf-8-sig")
validation_data.to_csv(split_folder / "validation.csv", index=False, encoding="utf-8-sig")
test_data.to_csv(split_folder / "test.csv", index=False, encoding="utf-8-sig")
# Build a single label mapping from the alphabetically sorted training classes.
class_names = sorted(train_data["label"].unique())
label2id = {name: number for number, name in enumerate(class_names)}
id2label = {number: name for name, number in label2id.items()}
for dataset in [train_data, validation_data, test_data]:
    dataset["label_id"] = dataset["label"].map(label2id).astype(int)
print("Class IDs:", label2id)
print(train_data[["sample_id", "label", "label_id"]].head(10))

# %% Build the SigLIP image datasets
from torch.utils.data import Dataset
from PIL import Image
from transformers import AutoProcessor
model_id = "google/siglip-base-patch16-224"
processor = AutoProcessor.from_pretrained(model_id)
# Read one labeled crop from the dataset DataFrame by integer row position.
# Return the processed RGB image tensor and its human-assigned class ID.
def read_image(dataset, index):
    sample = dataset.iloc[index]
    with Image.open(sample["image_path"]) as image:
        image = image.convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
    pixel_values = inputs["pixel_values"][0]
    label_id = int(sample["label_id"])
    return pixel_values, label_id
# Adapt one split to the input format expected by the classifier.
class ReportImageDataset(Dataset):
    def __init__(self, data):
        self.data = data
    def __len__(self):
        return len(self.data)
    def __getitem__(self, index):
        pixel_values, label_id = read_image(self.data, index)
        return {"pixel_values": pixel_values,"labels": label_id}
train_dataset = ReportImageDataset(train_data)
validation_dataset = ReportImageDataset(validation_data)
test_dataset = ReportImageDataset(test_data)
print("Training images:", len(train_dataset))
print("Validation images:", len(validation_dataset))
print("Test images:", len(test_dataset))

# %% Configure training and evaluation batches
from torch.utils.data import DataLoader

# Shuffle the training split and keep the original row order for evaluation.
batch_size = 8
train_loader = DataLoader(train_dataset,batch_size=batch_size,shuffle=True,num_workers=0)
validation_loader = DataLoader(validation_dataset,batch_size=batch_size,shuffle=False,num_workers=0)
test_loader = DataLoader(test_dataset,batch_size=batch_size,shuffle=False,num_workers=0)
# Check that a training batch contains the expected image and label tensors.
batch = next(iter(train_loader))
print("Image tensor shape:", batch["pixel_values"].shape)
print("Label tensor shape:", batch["labels"].shape)
print("True labels for this batch:", batch["labels"])

# %% Initialize the pretrained model for fine-tuning
import torch
from transformers import SiglipForImageClassification
from sklearn.metrics import accuracy_score, f1_score
from sklearn.metrics import classification_report, confusion_matrix

torch.manual_seed(42)

# Select CUDA, Apple MPS, or CPU in that order.
if torch.cuda.is_available():
    device = torch.device("cuda")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
else:
    device = torch.device("cpu")

print("Device:", device)

# Initialize a classification head for the class list using the pretrained SigLIP encoder.
model = SiglipForImageClassification.from_pretrained(
    model_id,
    num_labels=len(class_names),
    label2id=label2id,
    id2label=id2label,
    problem_type="single_label_classification"
)

# Freeze the encoder, then unfreeze its final two Transformer layers.
for parameter in model.vision_model.parameters():
    parameter.requires_grad = False

last_layers = model.vision_model.encoder.layers[-2:]
for parameter in last_layers.parameters():
    parameter.requires_grad = True

model = model.to(device)

# Fine-tune the final encoder layers at a lower learning rate than the new head.
optimizer = torch.optim.AdamW([
    {"params": last_layers.parameters(), "lr": 1e-5},
    {"params": model.classifier.parameters(), "lr": 1e-3}
])

epochs = 3
class_ids = list(range(len(class_names)))

save_folder = ROOT / "siglip_finetuned"
save_folder.mkdir(parents=True, exist_ok=True)


# %% Define the evaluation routine
# Evaluate the current model on a loader without updating its weights.
# Return the true and predicted class IDs in loader order for scoring.
def evaluate(loader):
    model.eval()
    true_labels = []
    predicted_labels = []

    with torch.no_grad():
        for batch in loader:
            pixels = batch["pixel_values"].to(device)
            outputs = model(pixel_values=pixels)
            predictions = outputs.logits.argmax(dim=1)
            true_labels.extend(batch["labels"].tolist())
            predicted_labels.extend(predictions.cpu().tolist())
    return true_labels, predicted_labels


# %% Train SigLIP and select the best checkpoint
best_f1 = -1
history = []

for epoch in range(1, epochs + 1):
    model.train()
    total_loss = 0
    total_images = 0

    for step, batch in enumerate(train_loader, start=1):
        pixels = batch["pixel_values"].to(device)
        labels = batch["labels"].to(device)

        # Zero the accumulated gradients before each batch update.
        optimizer.zero_grad()
        outputs = model(pixel_values=pixels, labels=labels)
        loss = outputs.loss
        loss.backward()
        optimizer.step()

        # Weight each batch loss by its image count to average over images.
        image_count = labels.size(0)
        total_loss += loss.item() * image_count
        total_images += image_count
        if step == 1 or step % 10 == 0 or step == len(train_loader):
            print(f"Epoch {epoch}/{epochs}, batch {step}/{len(train_loader)}, loss {loss.item():.4f}", flush=True)
    train_loss = total_loss / total_images
    # Measure validation accuracy and macro F1 after each training epoch.
    true_labels, predicted_labels = evaluate(validation_loader)
    val_accuracy = accuracy_score(true_labels, predicted_labels)
    val_f1 = f1_score(true_labels, predicted_labels,labels=class_ids, average="macro", zero_division=0)
    print(f"Epoch {epoch} complete. Training loss: {train_loss:.4f}, validation accuracy: {val_accuracy:.4f}, validation macro F1: {val_f1:.4f}")
    # Write the metrics by epoch and keep the checkpoint with the highest validation macro F1.
    history.append({"epoch": epoch,"train_loss": train_loss, "validation_accuracy": val_accuracy,"validation_macro_f1": val_f1})
    pds.DataFrame(history).to_csv(save_folder / "training_history.csv",index=False, encoding="utf-8-sig")
    if val_f1 > best_f1:
        best_f1 = val_f1
        model.save_pretrained(save_folder)
        processor.save_pretrained(save_folder)
        print("Saved the best checkpoint.")


# %% Evaluate the best checkpoint on the test split
del optimizer
model = SiglipForImageClassification.from_pretrained(save_folder).to(device)
true_labels, predicted_labels = evaluate(test_loader)
print("Test accuracy:", accuracy_score(true_labels, predicted_labels))
print(classification_report(
    true_labels,
    predicted_labels,
    labels=class_ids,
    target_names=class_names,
    zero_division=0
))
# Attach one predicted class and a correctness flag to each held-out crop.
test_results = test_data.copy()
test_results["predicted_label_id"] = predicted_labels
test_results["predicted_label"] = test_results["predicted_label_id"].map(id2label)
test_results["correct"] = test_results["label_id"] == test_results["predicted_label_id"]
test_results.to_csv(save_folder / "test_predictions.csv",index=False, encoding="utf-8-sig")
# Store the confusion matrix with true classes in rows and predicted classes in columns.
matrix = confusion_matrix(true_labels, predicted_labels, labels=class_ids)
pds.DataFrame(matrix, index=class_names, columns=class_names).to_csv(save_folder / "confusion_matrix.csv",index_label="true_label", encoding="utf-8-sig")
print("Saved the model and results to:", save_folder)

# %% Run the original SigLIP model as a zero-shot baseline
from transformers import AutoModel

# Define the text prompts for the zero-shot baseline using the same class names.
category_descriptions = {
    "Image": "A photograph of products, machinery, factories, buildings, nature, customers, or employees working.",
    "Team": "A formal portrait or posed group photograph of company executives, directors, or management.",
    "Chart": "A quantitative data chart, such as a bar chart, line chart, pie chart, or scatter plot.",
    "Map": "A geographic map showing locations, borders, place names, or business sites.",
    "Infographic": "An infographic combining icons, text, numbers, arrows, or diagrams to explain information.",
    "Logo": "A company logo, brand symbol, or stylized company name.",
    "Table": "A table of numerical or financial data arranged in rows and columns.",
    "Other": "Decorative artwork, an abstract background, or a decorative icon."
}

# Encode the prompts in class ID order so each score column maps to the correct class.
texts = [category_descriptions[name] for name in class_names]
text_inputs = processor(text=texts,padding="max_length",truncation=True,max_length=64,return_tensors="pt").to(device)
zero_shot_model = AutoModel.from_pretrained(model_id).to(device)
zero_shot_model.eval()
zero_shot_predictions = []
with torch.no_grad():
    for step, batch in enumerate(test_loader, start=1):
        outputs = zero_shot_model(
            pixel_values=batch["pixel_values"].to(device),
            **text_inputs
        )
        # Assign the class whose prompt has the highest image-text similarity.
        predicted_ids = outputs.logits_per_image.argmax(dim=1)
        zero_shot_predictions.extend(predicted_ids.cpu().tolist())
        print(f"Zero-shot inference: batch {step}/{len(test_loader)}", flush=True)
del zero_shot_model

# %% Classify report regions and construct visual measures
# Use the fine-tuned checkpoint and region manifest to classify crops and pages.
# Install the classifier dependencies in the project environment if needed.
# python -m pip install "transformers[torch]" torchvision sentencepiece pillow
import safetensors
import torch
import transformers
import pandas as pds
from transformers import SiglipForImageClassification, AutoProcessor
model = SiglipForImageClassification.from_pretrained(save_folder).to(device)
processor = AutoProcessor.from_pretrained(save_folder)
model.eval()
print("Loaded the fine-tuned SigLIP model.")
from pathlib import Path
from PIL import Image 
year = 2025
ROOT = Path.cwd()
if (ROOT / "annual_report_replication").is_dir():
    ROOT = ROOT / "annual_report_replication"
PNG_ROOT = ROOT / "annualreport——png"
regions_csv = PNG_ROOT/f"{year}_cropped_result"/"regions.csv"
df = pds.read_csv(regions_csv,dtype=str, keep_default_na=False)
classify_result = []
for test_path, company_gvkey in zip(df["crop_path"], df["gvkey"]):
    # Record the crop dimensions and preprocess the image for inference.
    with Image.open(test_path) as image:
        width, height = image.size
        test_image_rgb = image.convert("RGB")
        inputs = processor(images=test_image_rgb,return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    # Score all classes and retain the highest-probability class for the crop.
    scores = torch.softmax(outputs.logits, dim=1)[0]
    best_index = scores.argmax().item()
    highest_score = scores[best_index].item()
    predicted_category = model.config.id2label[best_index]
    area = width * height
    # Report the top class and confidence before adding the crop to the output.
    print("Predicted category:", predicted_category)
    print(f"Highest class probability: {highest_score:.4f}")
    classify_result.append({"year": year,"gvkey": company_gvkey,"crop_path": str(test_path),"region_areas": area,"predicted_category": predicted_category,"classification_score": highest_score})
classify_df = pds.DataFrame(classify_result)
classify_df["page_file"] = (classify_df["crop_path"].str.extract(r"(page_\d+)_", expand=False)+ ".png")
classify_df_path = PNG_ROOT/f"{year}_cropped_result"/"classified.csv"
classify_df.to_csv(classify_df_path,index=False,encoding="utf-8-sig")
# print("Saved:", classify_df_path)

# Keep the seven visual classes for aggregation, excluding Other.
visual_categories = ["Image", "Team", "Chart", "Map", "Infographic","Logo","Table"]
visual_regions = classify_df[classify_df["predicted_category"].isin(visual_categories)].copy()
# Sum crop areas in square pixels by firm, report year, page, and predicted class.
page_category_areas = (visual_regions.groupby(["year", "gvkey", "page_file", "predicted_category"])["region_areas"].sum().reset_index(name="category_area"))
# Assign each classified page to the class with the largest total crop area.
max_region_rows = (page_category_areas.loc[page_category_areas.groupby(["year", "gvkey", "page_file"])["category_area"].idxmax()].reset_index(drop=True))
page_category_path = PNG_ROOT/f"{year}_cropped_result"/"page_category.csv"
max_region_rows.to_csv(page_category_path,index=False,encoding="utf-8-sig")

# Count pages by firm and report year, with one column for each visual class.
company_year_counts = (max_region_rows.groupby(["year", "gvkey", "predicted_category"]).size().unstack(fill_value=0).reindex(columns=visual_categories, fill_value=0).reset_index())
company_year_path = (PNG_ROOT / f"{year}_cropped_result" / "company_year_counts.csv")
company_year_counts.to_csv(company_year_path,index=False,encoding="utf-8-sig")
