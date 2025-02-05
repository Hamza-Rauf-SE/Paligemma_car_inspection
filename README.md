# Car Inspection Model

This project contains a fine-tuned model designed to describe car damage using a custom dataset of images and their descriptions. The model is built using the Pali-Gemma small vision language model.

## Table of Contents
- [Introduction](#introduction)
- [Dataset](#dataset)
- [Installation](#installation)


## Introduction

The Car Inspection Model is a fine tuned pali-gemma small vision language model fine-tuned to detect and describe car damage from images. It leverages the Pali-Gemma for transfer learning and fine-tuning.

## Dataset

The dataset used for fine-tuning consists of car images with corresponding damage descriptions hosted on huggingface. Each image is labeled with detailed annotations of the damage.
```
from datasets import dataset
ds = dataset("kiranmalape/car_inspection")
```
## Installation

To set up the project, follow these steps:

1. Clone the repository:
```
git clone https://github.com/kiranknm/Paligemma_car_inspection.git
cd Paligemma_car_inspection
```
