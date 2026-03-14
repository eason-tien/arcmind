#!/usr/bin/env python3
"""
Simple video generation test - creates a basic animated video
"""
import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import os

def create_test_video(output_path="/tmp/test_video.mp4", duration_seconds=10, fps=24):
    """Create a simple animated test video"""
    
    print(f"Creating {duration_seconds}s test video at {fps} fps...")
    
    # Create frames
    frames = []
    total_frames = duration_seconds * fps
    
    for i in range(total_frames):
        # Create a colorful gradient frame
        img = Image.new('RGB', (1280, 720), 'black')
        draw = ImageDraw.Draw(img)
        
        # Animated color shift
        hue = (i / total_frames) * 360
        
        # Draw concentric circles with color animation
        for r in range(50, 600, 30):
            # Color based on frame
            red = int(127 + 127 * np.sin(i * 0.1 + r * 0.01))
            green = int(127 + 127 * np.sin(i * 0.1 + r * 0.02 + 2))
            blue = int(127 + 127 * np.sin(i * 0.1 + r * 0.03 + 4))
            
            # Draw ellipse
            x1 = 640 - r + int(50 * np.sin(i * 0.05))
            y1 = 360 - r + int(30 * np.cos(i * 0.05))
            x2 = 640 + r + int(50 * np.sin(i * 0.05))
            y2 = 360 + r + int(30 * np.cos(i * 0.05))
            
            draw.ellipse([x1, y1, x2, y2], fill=(red, green, blue))
        
        # Add text
        draw.text((540, 340), f"ArcMind Video Test", fill='white')
        draw.text((560, 380), f"Frame {i+1}/{total_frames}", fill='white')
        
        frames.append(img)
        
        if (i + 1) % 24 == 0:
            print(f"  Generated {i+1}/{total_frames} frames...")
    
    print("Saving video...")
    
    # Save as video using imageio or save frames
    try:
        import imageio
        # Save as video
        imageio.mimwrite(output_path, frames, fps=fps, codec='libx264', quality=8)
        print(f"Video saved to: {output_path}")
        return True
    except Exception as e:
        print(f"imageio failed: {e}")
        # Fallback: save as GIF
        gif_path = output_path.replace('.mp4', '.gif')
        print(f"Saving as GIF instead: {gif_path}")
        frames[0].save(gif_path, save_all=True, append_images=frames[1:100:5], duration=50, loop=0)
        return True

if __name__ == "__main__":
    print("="*50)
    print("ArcMind Video Generation Test")
    print("="*50)
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    print()
    
    # Create test video
    success = create_test_video()
    
    if success:
        print("\n✅ Test video created successfully!")
        # Get file size
        size = os.path.getsize("/tmp/test_video.mp4")
        print(f"File size: {size / 1024 / 1024:.2f} MB")
