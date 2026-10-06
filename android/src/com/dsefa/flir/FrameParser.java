package com.dsefa.flir;
import java.util.*;

public final class FrameParser {
    static final byte[] MAGIC={(byte)239,(byte)190,0,0};
    final Protocol.Buffer buffer=new Protocol.Buffer();
    public void add(byte[] bytes,int n){buffer.add(bytes,n);}
    public void clear(){buffer.length=0;}
    public Frame pop(){while(true){int p=buffer.find(MAGIC);
        if(p<0){if(buffer.length>3)buffer.drop(buffer.length-3);return null;}
        if(p>0)buffer.drop(p);if(buffer.length<28)return null;
        long size=Protocol.le32(buffer.data,8),thermal=Protocol.le32(buffer.data,12),jpg=Protocol.le32(buffer.data,16),status=Protocol.le32(buffer.data,20);
        if(size==0||size>2*1024*1024||thermal<39360||thermal+jpg+status>size){buffer.drop(4);continue;}
        int total=(int)size+28;if(buffer.length<total)return null;
        return new Frame(buffer.take(total),(int)thermal,(int)jpg,(int)status);
    }}
    public static final class Frame {
        public final byte[] record;public final int thermalSize,jpegSize,statusSize,jpegOffset,statusOffset;
        Frame(byte[] r,int thermal,int jpg,int status){record=r;thermalSize=thermal;jpegSize=jpg;statusSize=status;jpegOffset=28+thermal;statusOffset=jpegOffset+jpg;}
        public int[] thermal(){
            // Sensor packet layout, not a hardcoded overall frame/JPEG size.
            if(thermalSize<39360)throw new IllegalArgumentException("Short Gen2 thermal section");
            int[] raw=new int[19200];for(int y=0;y<120;y++)for(int x=0;x<160;x++){
                int p=32+y*328+(x<80?x*2:164+(x-80)*2);
                if(p+1>=28+thermalSize)throw new IllegalArgumentException("Thermal row out of section");
                raw[y*160+x]=Protocol.u(record[p])|(Protocol.u(record[p+1])<<8);
            }return raw;
        }
        public byte[] jpeg(){return Arrays.copyOfRange(record,jpegOffset,jpegOffset+jpegSize);}
        public byte[] status(){return Arrays.copyOfRange(record,statusOffset,statusOffset+statusSize);}
    }
}
