package com.dsefa.flir;
import java.io.*;
public final class RawArchive {
    public static final class Sample {public long timestamp;public int[] raw;}
    public static final class Writer implements Closeable {
        final DataOutputStream out;
        public Writer(OutputStream stream)throws IOException{out=new DataOutputStream(new BufferedOutputStream(stream));out.writeInt(0x46314131);}
        public synchronized void write(long timestamp,int[] raw)throws IOException {
            if(raw.length!=19200)throw new IOException("Expected 160x120 RAW samples");
            out.writeLong(timestamp);out.writeInt(raw.length);for(int v:raw)out.writeShort(v);
        }
        public synchronized void close()throws IOException{out.close();}
    }
    public static final class Reader implements Closeable {
        final DataInputStream in;
        public Reader(InputStream stream)throws IOException{in=new DataInputStream(new BufferedInputStream(stream));if(in.readInt()!=0x46314131)throw new IOException("Not a FLIR RAW archive");}
        public Sample next()throws IOException{
            int head=in.read();if(head<0)return null;
            long stamp=(long)head<<56;for(int i=6;i>=0;i--)stamp|=(long)in.readUnsignedByte()<<(i*8);
            int n=in.readInt();if(n!=19200)throw new IOException("Invalid RAW sample count");
            Sample s=new Sample();s.timestamp=stamp;s.raw=new int[n];for(int i=0;i<n;i++)s.raw[i]=in.readUnsignedShort();return s;
        }
        public void close()throws IOException{in.close();}
    }
}
