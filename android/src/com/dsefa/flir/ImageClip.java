package com.dsefa.flir;

import java.io.*;

/** Rendered-image recording. JPEG payloads are opaque; this format contains no RAW samples. */
public final class ImageClip {
    public static final int MAX_JPEG_BYTES=2*1024*1024;
    private static final int MAGIC=0x46314A31;
    private ImageClip(){}
    public static final class Sample {public long timestamp;public byte[] jpeg;}
    public static final class Writer implements Closeable {
        private final DataOutputStream output;
        private boolean hasTimestamp;
        private long previous;
        public Writer(OutputStream stream)throws IOException {
            output=new DataOutputStream(new BufferedOutputStream(stream));output.writeInt(MAGIC);
        }
        public synchronized void write(long timestamp,byte[] jpeg)throws IOException {
            if(jpeg==null||jpeg.length==0||jpeg.length>MAX_JPEG_BYTES)throw new IOException("Invalid clip JPEG length");
            if(hasTimestamp&&timestamp<previous)throw new IOException("Clip timestamps go backwards");
            output.writeLong(timestamp);output.writeInt(jpeg.length);output.write(jpeg);previous=timestamp;hasTimestamp=true;
        }
        public synchronized void close()throws IOException {output.close();}
    }
    /** Header-only validation with constant metadata memory. Sequential replay skips no prior records. */
    public static final class Reader implements Closeable {
        private final RandomAccessFile input;
        private final int count;
        private final long first,last,length;
        private int cursorIndex;
        private long cursorOffset=4;
        public Reader(File file)throws IOException {
            RandomAccessFile opened=new RandomAccessFile(file,"r");
            try {
                length=opened.length();
                if(length<4||opened.readInt()!=MAGIC)throw new IOException("Not a rendered FLIR image clip");
                long position=4,earliest=0,previous=0;int frames=0;
                while(position<length) {
                    if(length-position<12)throw new IOException("Truncated clip frame header");
                    opened.seek(position);long stamp=opened.readLong();int size=opened.readInt();
                    if(size<=0||size>MAX_JPEG_BYTES)throw new IOException("Invalid clip JPEG length");
                    if(size>length-position-12)throw new IOException("Truncated clip JPEG");
                    if(frames==0)earliest=stamp;else if(stamp<previous)throw new IOException("Clip timestamps go backwards");
                    if(frames==Integer.MAX_VALUE)throw new IOException("Too many clip frames");
                    previous=stamp;frames++;position+=12L+size;
                }
                if(frames==0)throw new IOException("Image clip contains no frames");
                input=opened;count=frames;first=earliest;last=previous;
            } catch(IOException|RuntimeException error) {
                try {opened.close();}catch(IOException closeError){error.addSuppressed(closeError);}throw error;
            }
        }
        public int count(){return count;}
        public long firstTimestamp(){return first;}
        public long lastTimestamp(){return last;}
        private void seek(int index)throws IOException {
            if(index<0||index>=count)throw new IndexOutOfBoundsException("Clip frame "+index+" of "+count);
            if(index<cursorIndex){cursorIndex=0;cursorOffset=4;}
            while(cursorIndex<index) {
                input.seek(cursorOffset+8);int size=input.readInt();
                validateSize(size,cursorOffset);cursorOffset+=12L+size;cursorIndex++;
            }
            input.seek(cursorOffset);
        }
        private void validateSize(int size,long offset)throws IOException {
            if(size<=0||size>MAX_JPEG_BYTES||size>length-offset-12)throw new IOException("Invalid or truncated clip JPEG");
        }
        public synchronized long timestamp(int index)throws IOException {seek(index);return input.readLong();}
        public synchronized Sample read(int index)throws IOException {
            seek(index);Sample sample=new Sample();sample.timestamp=input.readLong();int size=input.readInt();validateSize(size,cursorOffset);
            sample.jpeg=new byte[size];input.readFully(sample.jpeg);cursorOffset+=12L+size;cursorIndex=index+1;return sample;
        }
        public synchronized int nearest(long stamp)throws IOException {
            int low=0,high=count;
            while(low<high){int middle=low+(high-low)/2;if(timestamp(middle)<stamp)low=middle+1;else high=middle;}
            if(low==0)return 0;if(low==count)return count-1;
            return Long.compareUnsigned(stamp-timestamp(low-1),timestamp(low)-stamp)<=0?low-1:low;
        }
        public synchronized void close()throws IOException {input.close();}
    }
}
