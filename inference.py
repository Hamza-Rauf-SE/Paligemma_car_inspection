# -*- coding: utf-8 -*-
"""Inference.ipynb

Automatically generated by Colab.

"""

# Importing Libraries
import os
import sys
import site
from peft import PeftModel, PeftConfig
from transformers import AutoModelForCausalLM, PaliGemmaProcessor, AutoModelForPreTraining
from huggingface_hub import login
import torch
from PIL import Image
import requests

import huggingface_hub

# Set your Hugging Face token
huggingface_hub.login(token='****') # Replace with your actual token

# Load PeftConfig and base model
config = PeftConfig.from_pretrained("hamzakhan/paligemma_car_inspection")
base_model = AutoModelForPreTraining.from_pretrained("google/paligemma-3b-pt-224")
model = PeftModel.from_pretrained(base_model, "hamzakhan/paligemma_car_inspection")

# Loading and Processing the Image
input_text = "Describe this image"
input_image = Image.open('/content/0834_JPEG.rf.38503e82d09d0abd50648c0347c8584b.jpg')

# Loading PaliGemma Processor
processor = PaliGemmaProcessor.from_pretrained("google/paligemma-3b-pt-224")

# Preprocessing Inputs
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
inputs = processor(text=input_text, images=input_image, padding="longest", do_convert_rgb=True, return_tensors="pt").to(device)
model.to(device)
inputs = inputs.to(dtype=model.dtype)

# Generating and Decoding Output
with torch.no_grad():
    output = model.generate(**inputs, max_length=496)

print(processor.decode(output[0], skip_special_tokens=True))
