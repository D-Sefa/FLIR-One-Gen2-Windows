package com.dsefa.flir;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;

/** Fixed-size RAW archive access. Only the requested frame is decoded into memory. */
public final class RecordingIndex implements Closeable {
    private static final int MAGIC=0x46314131, PIXELS=19200;
    private static final long HEADER=4, RECORD=12+PIXELS*2;
    private final RandomAccessFile input;
    private final int count;
    private final long first,last;

    public RecordingIndex(File file)throws IOException {
        RandomAccessFile opened=new RandomAccessFile(file,"r");
        try {
            long length=opened.length();
            if(length<HEADER||opened.readInt()!=MAGIC)throw new IOException("Not a FLIR RAW archive");
            long frames=(length-HEADER)/RECORD;
            if((length-HEADER)%RECORD!=0)throw new IOException("Truncated RAW archive frame");
            if(frames==0)throw new IOException("RAW archive contains no frames");
            if(frames>Integer.MAX_VALUE)throw new IOException("RAW archive has too many frames");
            long earliest=0,previous=0;
            for(int i=0;i<(int)frames;i++) {
                opened.seek(HEADER+i*RECORD);
                long stamp=opened.readLong();
                if(opened.readInt()!=PIXELS)throw new IOException("Invalid RAW sample count at frame "+i);
                if(i==0)earliest=stamp;
                else if(stamp<previous)throw new IOException("RAW timestamps go backwards at frame "+i);
                previous=stamp;
            }
            input=opened;count=(int)frames;first=earliest;last=previous;
        } catch(IOException|RuntimeException error) {
            try {opened.close();}catch(IOException closeError){error.addSuppressed(closeError);}
            throw error;
        }
    }
    public int count(){return count;}
    public long firstTimestamp(){return first;}
    public long lastTimestamp(){return last;}
    public synchronized long timestamp(int index)throws IOException {
        check(index);input.seek(HEADER+index*RECORD);return input.readLong();
    }
    public synchronized RawArchive.Sample read(int index)throws IOException {
        check(index);input.seek(HEADER+index*RECORD);
        RawArchive.Sample sample=new RawArchive.Sample();sample.timestamp=input.readLong();
        if(input.readInt()!=PIXELS)throw new IOException("Invalid RAW sample count at frame "+index);
        sample.raw=new int[PIXELS];
        byte[] bytes=new byte[PIXELS*2];input.readFully(bytes);
        for(int i=0;i<PIXELS;i++)sample.raw[i]=((bytes[i*2]&255)<<8)|(bytes[i*2+1]&255);
        return sample;
    }
    /** Returns the first matching frame; equally distant times choose the earlier frame. */
    public synchronized int nearest(long stamp)throws IOException {
        int low=0,high=count;
        while(low<high) {
            int middle=low+(high-low)/2;
            if(timestamp(middle)<stamp)low=middle+1;else high=middle;
        }
        if(low==0)return 0;
        if(low==count)return count-1;
        long after=timestamp(low),before=timestamp(low-1);
        if(Long.compareUnsigned(stamp-before,after-stamp)>0)return low;
        // A duplicate earlier timestamp should also select its first frame.
        int left=0,right=low-1;
        while(left<right){int middle=left+(right-left)/2;if(timestamp(middle)<before)left=middle+1;else right=middle;}
        return left;
    }
    private void check(int index){if(index<0||index>=count)throw new IndexOutOfBoundsException("Frame "+index+" of "+count);}
    public synchronized void close()throws IOException{input.close();}
}
