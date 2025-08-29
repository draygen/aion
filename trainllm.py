from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer
from transformers import BitsAndBytesConfig
from datasets import load_dataset
from peft import get_peft_model, LoraConfig, TaskType
import torch
import os

print("Loading dataset...")
dataset = load_dataset("mlabonne/guanaco-llama2-1k", split="train")

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained("mistralai/Mistral-7B-v0.1")
tokenizer.pad_token = tokenizer.eos_token

print("Loading model with 4-bit quantization...")
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
)

model = AutoModelForCausalLM.from_pretrained(
    "mistralai/Mistral-7B-v0.1",
    quantization_config=bnb_config,
    device_map="auto"
)

print("Applying LoRA configuration...")
peft_config = LoraConfig(
    r=8,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type=TaskType.CAUSAL_LM
)

model = get_peft_model(model, peft_config)

print("Tokenizing dataset...")
def tokenize(batch):
    output = tokenizer(batch["text"], padding="max_length", truncation=True, max_length=512)
    output["labels"] = output["input_ids"].copy()
    return output

tokenized = dataset.map(tokenize, batched=True)
tokenized.set_format("torch", columns=["input_ids", "attention_mask", "labels"])

print("Setting up training...")
training_args = TrainingArguments(
    output_dir="./lora_mistral_output",
    per_device_train_batch_size=1,
    gradient_accumulation_steps=2,
    warmup_steps=10,
    num_train_epochs=1,
    logging_dir="./logs",
    save_strategy="epoch",
    logging_steps=5,
    learning_rate=2e-4,
    bf16=True if torch.cuda.is_available() else False,
    fp16=not torch.cuda.is_bf16_supported(),
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized,
)

print("Starting training...")
trainer.train()